"""Constants for the Solkart integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "solkart"

# Solkart API base URL.
API_BASE_URL: Final = "https://api.solkart.no"

# Config entry data keys.
CONF_API_KEY: Final = "api_key"
CONF_LATITUDE: Final = "latitude"
CONF_LONGITUDE: Final = "longitude"
CONF_ARRAYS: Final = "arrays"

# Per-array keys (stored inside each item of CONF_ARRAYS).
CONF_ARRAY_NAME: Final = "name"
CONF_ARRAY_KWP: Final = "kwp"
CONF_ARRAY_TILT: Final = "tilt_deg"
CONF_ARRAY_AZIMUTH: Final = "azimuth_deg"

# Config flow helper.
CONF_ADD_ANOTHER: Final = "add_another"

# Options keys.
CONF_PERFORMANCE_RATIO: Final = "performance_ratio"
CONF_UPDATE_INTERVAL: Final = "update_interval_minutes"
CONF_DAILY: Final = "daily"
CONF_EXTENDED: Final = "extended"

# Defaults.
DEFAULT_PERFORMANCE_RATIO: Final = 0.85
DEFAULT_UPDATE_INTERVAL_MINUTES: Final = 60
MIN_UPDATE_INTERVAL_MINUTES: Final = 15
MAX_UPDATE_INTERVAL_MINUTES: Final = 360
DEFAULT_ARRAY_NAME: Final = "Tak"

# Request timeout in seconds.
REQUEST_TIMEOUT: Final = 30

# Integration version (keep in sync with manifest.json) and the User-Agent we
# send. Solkart sits behind Cloudflare, which blocks some default UAs (notably
# python-urllib); an explicit UA both identifies us and avoids that.
VERSION: Final = "0.1.1"
USER_AGENT: Final = f"ha-solkart/{VERSION}"

# How long the manufacturer string stays.
MANUFACTURER: Final = "Solkart"

# Used for fallback update interval inside the coordinator.
DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=DEFAULT_UPDATE_INTERVAL_MINUTES)
