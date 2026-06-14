"""DataUpdateCoordinator for the Solkart integration."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

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
    DEFAULT_PERFORMANCE_RATIO,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)
from .model import ForecastPoint, SolkartData, parse_forecast

_LOGGER = logging.getLogger(__name__)

type SolkartConfigEntry = ConfigEntry[SolkartDataUpdateCoordinator]

# How much of the merged forecast series to retain around "now". The API only
# returns the timeseries from the latest model cycle forward, so to keep a
# full-day curve (incl. the already-elapsed morning) we accumulate points across
# polls and persist them. The past window bounds attribute/DB size; long-term
# comparison lives in the recorder statistics, not this buffer.
_RETAIN_PAST = timedelta(hours=48)
_RETAIN_FUTURE = timedelta(hours=84)
_STORAGE_VERSION = 1


class SolkartDataUpdateCoordinator(DataUpdateCoordinator[SolkartData]):
    """Coordinator that fetches, parses and accumulates Solkart forecasts."""

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
        # Merged forecast points keyed by their (aware, UTC) hour timestamp,
        # persisted so a restart does not lose the already-elapsed hours that
        # the API will never return again.
        self._merged: dict[datetime, ForecastPoint] = {}
        self._store: Store = Store(
            hass,
            _STORAGE_VERSION,
            f"{DOMAIN}.{config_entry.entry_id}.forecast_points",
        )
        self._loaded = False

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

    # -- merged-history persistence ---------------------------------------

    async def _ensure_loaded(self) -> None:
        """Load the persisted forecast points once, on first update."""
        if self._loaded:
            return
        self._loaded = True
        stored = await self._store.async_load()
        if not stored:
            return
        for item in stored.get("points", []):
            try:
                ts = datetime.fromisoformat(item["t"])
            except (KeyError, ValueError):
                continue
            self._merged[ts] = ForecastPoint(
                timestamp=ts,
                ghi_wm2=item.get("ghi"),
                total_w=item.get("w"),
                total_kwh=item.get("kwh"),
                array_w=item.get("arr") or {},
            )

    def _absorb(self, points: list[ForecastPoint]) -> list[ForecastPoint]:
        """Merge a fresh cycle's points and prune to the retention window.

        A new cycle only carries keys from its cycle_time forward, so it
        overwrites the current/future hours while leaving the already-elapsed
        hours of today untouched (retained from when they were last forecast).
        """
        for point in points:
            self._merged[point.timestamp] = point
        now = dt_util.utcnow()
        low = now - _RETAIN_PAST
        high = now + _RETAIN_FUTURE
        self._merged = {
            ts: pt for ts, pt in self._merged.items() if low <= ts <= high
        }
        return sorted(self._merged.values(), key=lambda p: p.timestamp)

    def _serialize(self) -> dict:
        return {
            "points": [
                {
                    "t": p.timestamp.isoformat(),
                    "ghi": p.ghi_wm2,
                    "w": p.total_w,
                    "kwh": p.total_kwh,
                    "arr": p.array_w,
                }
                for p in self._merged.values()
            ]
        }

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
        data = parse_forecast(raw)

        # Accumulate across cycles so the series spans the whole day (and the
        # recent past), then hand the sensors the merged view.
        await self._ensure_loaded()
        merged_points = self._absorb(data.points)
        await self._store.async_save(self._serialize())
        return replace(data, points=merged_points)
