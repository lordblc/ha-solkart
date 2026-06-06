"""Energy dashboard platform for Solkart.

Home Assistant discovers solar-forecast providers by importing each
integration's ``energy.py`` module (via ``async_process_integration_platforms``)
and looking for ``async_get_solar_forecast``. Defining it here is what makes
Solkart selectable as a "Solar production forecast" in the Energy dashboard.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .coordinator import SolkartConfigEntry, SolkartDataUpdateCoordinator


async def async_get_solar_forecast(
    hass: HomeAssistant, config_entry_id: str
) -> dict[str, dict[str, float]] | None:
    """Return a solar production forecast for the HA Energy dashboard."""
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
