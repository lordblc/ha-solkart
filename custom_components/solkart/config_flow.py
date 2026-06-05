"""Config and options flow for the Solkart integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import SolkartApiClient, SolkartAuthError, SolkartError
from .const import (
    CONF_ADD_ANOTHER,
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
    DEFAULT_ARRAY_NAME,
    DEFAULT_PERFORMANCE_RATIO,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    MAX_UPDATE_INTERVAL_MINUTES,
    MIN_UPDATE_INTERVAL_MINUTES,
)


def _array_schema(default_name: str) -> vol.Schema:
    """Schema for entering a single PV array."""
    return vol.Schema(
        {
            vol.Required(CONF_ARRAY_NAME, default=default_name): str,
            vol.Required(CONF_ARRAY_KWP, default=5.0): NumberSelector(
                NumberSelectorConfig(
                    min=0.1,
                    max=10000,
                    step=0.1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="kWp",
                )
            ),
            vol.Required(CONF_ARRAY_TILT, default=30): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=90, step=1, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(CONF_ARRAY_AZIMUTH, default=180): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=360, step=1, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Optional(CONF_ADD_ANOTHER, default=False): bool,
        }
    )


class SolkartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Solkart configuration flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._arrays: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: credentials and location."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = SolkartApiClient(
                user_input[CONF_API_KEY], async_get_clientsession(self.hass)
            )
            try:
                await client.validate(
                    latitude=user_input[CONF_LATITUDE],
                    longitude=user_input[CONF_LONGITUDE],
                )
            except SolkartAuthError:
                errors["base"] = "invalid_auth"
            except SolkartError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_LATITUDE]:.4f}_{user_input[CONF_LONGITUDE]:.4f}"
                )
                self._abort_if_unique_id_configured()
                self._data = dict(user_input)
                self._arrays = []
                return await self.async_step_array()

        suggested = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_API_KEY, default=suggested.get(CONF_API_KEY, "")
                ): str,
                vol.Required(
                    CONF_LATITUDE,
                    default=suggested.get(
                        CONF_LATITUDE, self.hass.config.latitude
                    ),
                ): cv.latitude,
                vol.Required(
                    CONF_LONGITUDE,
                    default=suggested.get(
                        CONF_LONGITUDE, self.hass.config.longitude
                    ),
                ): cv.longitude,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_array(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Repeatable step: add one PV array, optionally loop for more."""
        if user_input is not None:
            add_another = user_input.pop(CONF_ADD_ANOTHER, False)
            self._arrays.append(
                {
                    CONF_ARRAY_NAME: user_input[CONF_ARRAY_NAME],
                    CONF_ARRAY_KWP: user_input[CONF_ARRAY_KWP],
                    CONF_ARRAY_TILT: int(user_input[CONF_ARRAY_TILT]),
                    CONF_ARRAY_AZIMUTH: int(user_input[CONF_ARRAY_AZIMUTH]),
                }
            )
            if add_another:
                return await self.async_step_array()

            lat = self._data[CONF_LATITUDE]
            lon = self._data[CONF_LONGITUDE]
            return self.async_create_entry(
                title=f"Solkart ({lat:.2f}, {lon:.2f})",
                data={**self._data, CONF_ARRAYS: self._arrays},
            )

        default_name = (
            DEFAULT_ARRAY_NAME
            if not self._arrays
            else f"Array {len(self._arrays) + 1}"
        )
        return self.async_show_form(
            step_id="array",
            data_schema=_array_schema(default_name),
            description_placeholders={"count": str(len(self._arrays))},
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when the API key is rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh API key and validate it."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            client = SolkartApiClient(
                user_input[CONF_API_KEY], async_get_clientsession(self.hass)
            )
            try:
                await client.validate(
                    latitude=entry.data[CONF_LATITUDE],
                    longitude=entry.data[CONF_LONGITUDE],
                )
            except SolkartAuthError:
                errors["base"] = "invalid_auth"
            except SolkartError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_API_KEY: user_input[CONF_API_KEY]},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> SolkartOptionsFlow:
        """Return the options flow handler."""
        return SolkartOptionsFlow()


class SolkartOptionsFlow(OptionsFlow):
    """Handle Solkart options (tuning and polling)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage performance ratio, polling interval and Basic+ toggles."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PERFORMANCE_RATIO,
                    default=options.get(
                        CONF_PERFORMANCE_RATIO, DEFAULT_PERFORMANCE_RATIO
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.1, max=1.0, step=0.01, mode=NumberSelectorMode.SLIDER
                    )
                ),
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=options.get(
                        CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_UPDATE_INTERVAL_MINUTES,
                        max=MAX_UPDATE_INTERVAL_MINUTES,
                        step=5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Required(
                    CONF_DAILY, default=options.get(CONF_DAILY, False)
                ): bool,
                vol.Required(
                    CONF_EXTENDED, default=options.get(CONF_EXTENDED, False)
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
