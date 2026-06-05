"""The Solkart solar-forecast integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import SolkartConfigEntry, SolkartDataUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: SolkartConfigEntry
) -> bool:
    """Set up Solkart from a config entry."""
    coordinator = SolkartDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SolkartConfigEntry
) -> bool:
    """Unload a Solkart config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: SolkartConfigEntry
) -> None:
    """Reload the entry when its options change (e.g. update interval)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_get_solar_forecast(
    hass: HomeAssistant, config_entry_id: str
) -> dict[str, dict[str, float]] | None:
    """Return a solar production forecast for the HA Energy dashboard.

    The Energy dashboard calls this for any config entry whose domain exposes
    it, letting the user pick Solkart as a "Solar production forecast".
    """
    entry: SolkartConfigEntry | None = hass.config_entries.async_get_entry(
        config_entry_id
    )
    if entry is None:
        return None
    coordinator: SolkartDataUpdateCoordinator | None = getattr(
        entry, "runtime_data", None
    )
    if coordinator is None or coordinator.data is None:
        return None
    return {"wh_hours": coordinator.data.wh_hours()}
