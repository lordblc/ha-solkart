"""DataUpdateCoordinator for the Solkart integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    SolkartApiClient,
    SolkartAuthError,
    SolkartError,
    SolkartRateLimitError,
)
from .const import (
    CONF_API_KEY,
    CONF_ARRAY_AZIMUTH,
    CONF_ARRAY_KWP,
    CONF_ARRAY_NAME,
    CONF_ARRAY_TILT,
    CONF_ARRAYS,
    CONF_DAILY,
    CONF_EXTENDED,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_PERFORMANCE_RATIO,
    CONF_UPDATE_INTERVAL,
    DEFAULT_PERFORMANCE_RATIO,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
)
from .model import SolkartData, parse_forecast

_LOGGER = logging.getLogger(__name__)

type SolkartConfigEntry = ConfigEntry[SolkartDataUpdateCoordinator]


class SolkartDataUpdateCoordinator(DataUpdateCoordinator[SolkartData]):
    """Coordinator that fetches and parses Solkart forecasts."""

    config_entry: SolkartConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: SolkartConfigEntry
    ) -> None:
        """Initialise the coordinator from a config entry."""
        self.client = SolkartApiClient(
            api_key=config_entry.data[CONF_API_KEY],
            session=async_get_clientsession(hass),
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=self._interval_from_options(config_entry),
        )
        self._rate_limit_warned = False

    @staticmethod
    def _interval_from_options(config_entry: SolkartConfigEntry) -> timedelta:
        minutes = config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES
        )
        return timedelta(minutes=minutes)

    def _build_arrays(self) -> list[dict]:
        arrays = []
        for item in self.config_entry.data[CONF_ARRAYS]:
            arrays.append(
                {
                    "name": item[CONF_ARRAY_NAME],
                    "kwp": item[CONF_ARRAY_KWP],
                    "tilt_deg": item[CONF_ARRAY_TILT],
                    "azimuth_deg": item[CONF_ARRAY_AZIMUTH],
                }
            )
        return arrays

    async def _async_update_data(self) -> SolkartData:
        entry = self.config_entry
        options = entry.options
        try:
            raw = await self.client.forecast(
                latitude=entry.data[CONF_LATITUDE],
                longitude=entry.data[CONF_LONGITUDE],
                arrays=self._build_arrays(),
                performance_ratio=options.get(
                    CONF_PERFORMANCE_RATIO, DEFAULT_PERFORMANCE_RATIO
                ),
                daily=options.get(CONF_DAILY, False),
                extended=options.get(CONF_EXTENDED, False),
            )
        except SolkartAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SolkartRateLimitError as err:
            if not self._rate_limit_warned:
                _LOGGER.warning(
                    "Solkart API rate limit hit; consider raising the update "
                    "interval in the integration options. (%s)",
                    err,
                )
                self._rate_limit_warned = True
            raise UpdateFailed(str(err)) from err
        except SolkartError as err:
            raise UpdateFailed(str(err)) from err

        self._rate_limit_warned = False
        return parse_forecast(raw)
