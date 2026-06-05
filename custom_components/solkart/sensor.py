"""Sensor platform for the Solkart integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfEnergy,
    UnitOfIrradiance,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_ARRAY_NAME, CONF_ARRAYS, DOMAIN, MANUFACTURER
from .coordinator import SolkartConfigEntry, SolkartDataUpdateCoordinator
from .model import SolkartData

# One hour offset used by the "next hour" power sensor.
ONE_HOUR = timedelta(hours=1)


@dataclass(frozen=True, kw_only=True)
class SolkartSensorEntityDescription(SensorEntityDescription):
    """Describes a Solkart sensor and how to derive its value."""

    value_fn: Callable[[SolkartData, datetime], StateType | datetime]
    attributes_fn: Callable[[SolkartData], dict] | None = None


SENSOR_DESCRIPTIONS: tuple[SolkartSensorEntityDescription, ...] = (
    SolkartSensorEntityDescription(
        key="power_production_now",
        translation_key="power_production_now",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data, now: data.power_now(now),
        attributes_fn=lambda data: {
            "cycle_time": data.cycle_time.isoformat() if data.cycle_time else None,
            "data_mode": data.data_mode,
            "engine": data.engine,
            "forecast": data.forecast_attribute(),
        },
    ),
    SolkartSensorEntityDescription(
        key="power_production_next_hour",
        translation_key="power_production_next_hour",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        value_fn=lambda data, now: data.power_at(now, ONE_HOUR),
    ),
    SolkartSensorEntityDescription(
        key="ghi_now",
        translation_key="ghi_now",
        device_class=SensorDeviceClass.IRRADIANCE,
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data, now: data.ghi_now(now),
    ),
    SolkartSensorEntityDescription(
        key="energy_production_today",
        translation_key="energy_production_today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data, now: data.energy_today(now),
    ),
    SolkartSensorEntityDescription(
        key="energy_production_today_remaining",
        translation_key="energy_production_today_remaining",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data, now: data.energy_today_remaining(now),
    ),
    SolkartSensorEntityDescription(
        key="energy_production_tomorrow",
        translation_key="energy_production_tomorrow",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data, now: data.energy_tomorrow(now),
    ),
    SolkartSensorEntityDescription(
        key="energy_current_hour",
        translation_key="energy_current_hour",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data, now: data.energy_current_hour(now),
    ),
    SolkartSensorEntityDescription(
        key="energy_next_hour",
        translation_key="energy_next_hour",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data, now: data.energy_next_hour(now),
    ),
    SolkartSensorEntityDescription(
        key="power_highest_peak_time_today",
        translation_key="power_highest_peak_time_today",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, now: data.peak_time_today(now),
    ),
    SolkartSensorEntityDescription(
        key="power_highest_peak_time_tomorrow",
        translation_key="power_highest_peak_time_tomorrow",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, now: data.peak_time_tomorrow(now),
    ),
    SolkartSensorEntityDescription(
        key="peak_power",
        translation_key="peak_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data, now: data.peak_power_w,
    ),
    SolkartSensorEntityDescription(
        key="forecast_cycle_time",
        translation_key="forecast_cycle_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data, now: data.cycle_time,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolkartConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Solkart sensors from a config entry."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = [
        SolkartSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    ]

    # Per-array "power now" sensors are only useful when there is more than
    # one array (otherwise they would duplicate the total).
    arrays = entry.data[CONF_ARRAYS]
    if len(arrays) > 1:
        entities.extend(
            SolkartArrayPowerSensor(coordinator, array[CONF_ARRAY_NAME])
            for array in arrays
        )

    async_add_entities(entities)


def _device_info(coordinator: SolkartDataUpdateCoordinator) -> DeviceInfo:
    entry = coordinator.config_entry
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=MANUFACTURER,
        model="Solar forecast",
        configuration_url="https://solkart.no",
    )


class SolkartSensor(
    CoordinatorEntity[SolkartDataUpdateCoordinator], SensorEntity
):
    """A Solkart sensor backed by the shared coordinator data."""

    entity_description: SolkartSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolkartDataUpdateCoordinator,
        description: SolkartSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{description.key}"
        )
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> StateType | datetime:
        """Return the derived value for the current time."""
        return self.entity_description.value_fn(self.coordinator.data, dt_util.now())

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return extra attributes (forecast series) when defined."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)


class SolkartArrayPowerSensor(
    CoordinatorEntity[SolkartDataUpdateCoordinator], SensorEntity
):
    """Per-array instantaneous power sensor."""

    _attr_has_entity_name = True
    _attr_translation_key = "array_power_now"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(
        self, coordinator: SolkartDataUpdateCoordinator, array_name: str
    ) -> None:
        super().__init__(coordinator)
        self._array_name = array_name
        self._attr_translation_placeholders = {"array_name": array_name}
        slug = array_name.lower().replace(" ", "_")
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_array_{slug}_power_now"
        )
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> StateType:
        """Return the interpolated power for this array right now."""
        return self.coordinator.data.power_array_now(dt_util.now(), self._array_name)
