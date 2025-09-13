"""Config flow to configure Portainer."""
from __future__ import annotations

import re
from logging import getLogger
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_SSL,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import PortainerAPI
from .const import (
    CONF_FEATURE_HEALTH_CHECK,  # feature switch
    CONF_FEATURE_RESTART_POLICY,
    CONF_FEATURE_UPDATE_CHECK,
    CONF_UPDATE_CHECK_TIME,
    DEFAULT_DEVICE_NAME,
    DEFAULT_FEATURE_HEALTH_CHECK,
    DEFAULT_FEATURE_RESTART_POLICY,
    DEFAULT_FEATURE_UPDATE_CHECK,
    DEFAULT_HOST,
    DEFAULT_SSL,
    DEFAULT_SSL_VERIFY,
    DEFAULT_UPDATE_CHECK_TIME,
    DOMAIN,
    # naming option
    CONF_CONTAINER_SENSOR_NAME_MODE,
    DEFAULT_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
    NAME_MODE_STACK_SERVICE,
)

_LOGGER = getLogger(__name__)


def validate_time_string(value):
    """Validate time string in HH:MM format."""
    if not isinstance(value, str):
        raise vol.Invalid("Time must be a string in HH:MM format")

    time_pattern = re.compile(r"^([01]?\d|2[0-3]):([0-5]?\d)$")
    match = time_pattern.match(value)

    if not match:
        raise vol.Invalid("Time must be in HH:MM format (e.g., 04:30)")

    hours = int(match.group(1))
    minutes = int(match.group(2))

    if not (0 <= hours <= 23):
        raise vol.Invalid("Hours must be between 0 and 23")
    if not (0 <= minutes <= 59):
        raise vol.Invalid("Minutes must be between 0 and 59")

    return value


@callback
def configured_instances(hass):
    """Return a set of configured instances."""
    return {entry.data[CONF_NAME] for entry in hass.config_entries.async_entries(DOMAIN)}


class PortainerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """PortainerConfigFlow class."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_import(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Occurs when a previous entry setup fails and is re-initiated."""
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle a flow initialized by the user."""
        errors = {}
        if user_input is not None:
            if user_input[CONF_NAME] in configured_instances(self.hass):
                errors["base"] = "name_exists"
                return self._show_config_form(user_input=user_input, errors=errors)

            api = await self.hass.async_add_executor_job(
                PortainerAPI,
                self.hass,
                user_input[CONF_HOST],
                user_input[CONF_API_KEY],
                user_input[CONF_SSL],
                user_input[CONF_VERIFY_SSL],
            )

            conn, errorcode = await self.hass.async_add_executor_job(api.connection_test)
            if not conn:
                errors[CONF_HOST] = errorcode
                _LOGGER.error("Portainer connection error (%s)", errorcode)

            if not errors:
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

            return self._show_config_form(user_input=user_input, errors=errors)

        return self._show_config_form(
            user_input={
                CONF_NAME: DEFAULT_DEVICE_NAME,
                CONF_HOST: DEFAULT_HOST,
                CONF_API_KEY: "",
                CONF_SSL: DEFAULT_SSL,
                CONF_VERIFY_SSL: DEFAULT_SSL_VERIFY,
            },
            errors=errors,
        )

    def _show_config_form(self, user_input: dict[str, Any] | None, errors: dict[str, Any] | None = None) -> FlowResult:
        """Show the configuration form."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=user_input[CONF_NAME]): str,
                    vol.Required(CONF_HOST, default=user_input[CONF_HOST]): str,
                    vol.Required(CONF_API_KEY, default=user_input[CONF_API_KEY]): str,
                    vol.Optional(CONF_SSL, default=user_input[CONF_SSL]): bool,
                    vol.Optional(CONF_VERIFY_SSL, default=user_input[CONF_VERIFY_SSL]): bool,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PortainerOptionsFlow(config_entry)


class PortainerOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Portainer."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}

        if user_input is not None:
            # Validate update time only when feature enabled
            if user_input.get(CONF_FEATURE_UPDATE_CHECK) and CONF_UPDATE_CHECK_TIME in user_input:
                time_str = user_input[CONF_UPDATE_CHECK_TIME]
                try:
                    import time
                    time.strptime(time_str, "%H:%M")
                except ValueError:
                    errors[CONF_UPDATE_CHECK_TIME] = "invalid_time_format"

            if not errors:
                # Merge with existing options to avoid losing unknown keys
                merged = {**self.config_entry.options, **user_input}
                return self.async_create_entry(title="", data=merged)

        current_data = self.config_entry.options or {}
        return await self._show_form_with_static_schema(current_data, errors)

    async def _show_form_with_static_schema(self, data, errors=None):
        """Show form with static schema - all fields visible."""
        # Labeled dropdown for container entity naming across **sensors, switches, and restart buttons**
        name_selector = SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(
                        value=NAME_MODE_SERVICE,
                        label="Compose service (shortest, e.g. 'web')",
                    ),
                    SelectOptionDict(
                        value=NAME_MODE_CONTAINER,
                        label="Container name (e.g. 'my_container')",
                    ),
                    SelectOptionDict(
                        value=NAME_MODE_STACK_SERVICE,
                        label="Stack/Service (e.g. 'myapp/web')",
                    ),
                ],
                multiple=False,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )

        schema_dict = {
            vol.Optional(
                CONF_FEATURE_HEALTH_CHECK,
                default=data.get(CONF_FEATURE_HEALTH_CHECK, DEFAULT_FEATURE_HEALTH_CHECK),
            ): bool,
            vol.Optional(
                CONF_FEATURE_RESTART_POLICY,
                default=data.get(CONF_FEATURE_RESTART_POLICY, DEFAULT_FEATURE_RESTART_POLICY),
            ): bool,
            vol.Optional(
                CONF_FEATURE_UPDATE_CHECK,
                default=data.get(CONF_FEATURE_UPDATE_CHECK, DEFAULT_FEATURE_UPDATE_CHECK),
            ): bool,
            vol.Optional(
                CONF_UPDATE_CHECK_TIME,
                default=data.get(CONF_UPDATE_CHECK_TIME, DEFAULT_UPDATE_CHECK_TIME),
            ): str,
            vol.Optional(
                CONF_CONTAINER_SENSOR_NAME_MODE,
                default=data.get(
                    CONF_CONTAINER_SENSOR_NAME_MODE, DEFAULT_CONTAINER_SENSOR_NAME_MODE
                ),
            ): name_selector,
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )
