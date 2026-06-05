"""Diagnostics support for the Solkart integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, CONF_LATITUDE, CONF_LONGITUDE
from .coordinator import SolkartConfigEntry

TO_REDACT = {CONF_API_KEY, CONF_LATITUDE, CONF_LONGITUDE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SolkartConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry (secrets redacted)."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "forecast": None
        if data is None
        else {
            "cycle_time": data.cycle_time.isoformat() if data.cycle_time else None,
            "data_mode": data.data_mode,
            "model": data.model,
            "engine": data.engine,
            "peak_power_w": data.peak_power_w,
            "total_production_kwh": data.total_production_kwh,
            "array_names": data.array_names,
            "point_count": len(data.points),
            "series": data.forecast_attribute(),
        },
    }
