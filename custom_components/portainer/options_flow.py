# file: custom_components/portainer/options_flow.py
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries

from .const import (
    DOMAIN,
    # Existing options (kept/merged on save)
    CONF_FEATURE_HEALTH_CHECK,
    CONF_FEATURE_RESTART_POLICY,
    CONF_FEATURE_UPDATE_CHECK,
    CONF_UPDATE_CHECK_TIME,
    # New naming option
    CONF_CONTAINER_SENSOR_NAME_MODE,
    DEFAULT_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
    NAME_MODE_STACK_SERVICE,
)

NAME_MODE_OPTIONS = {
    NAME_MODE_SERVICE: "Compose service (recommended)",
    NAME_MODE_CONTAINER: "Container name",
    NAME_MODE_STACK_SERVICE: "Stack/Service",
}


class PortainerOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            # Merge with existing to avoid dropping unknown/legacy keys
            data = {**self.config_entry.options, **user_input}
            return self.async_create_entry(title="", data=data)

        opts = {**self.config_entry.options}
        defaults = {
            CONF_FEATURE_HEALTH_CHECK: opts.get(CONF_FEATURE_HEALTH_CHECK, True),
            CONF_FEATURE_RESTART_POLICY: opts.get(CONF_FEATURE_RESTART_POLICY, True),
            CONF_FEATURE_UPDATE_CHECK: opts.get(CONF_FEATURE_UPDATE_CHECK, True),
            CONF_UPDATE_CHECK_TIME: opts.get(CONF_UPDATE_CHECK_TIME, "04:30"),
            CONF_CONTAINER_SENSOR_NAME_MODE: opts.get(
                CONF_CONTAINER_SENSOR_NAME_MODE, DEFAULT_CONTAINER_SENSOR_NAME_MODE
            ),
        }

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_FEATURE_HEALTH_CHECK, default=defaults[CONF_FEATURE_HEALTH_CHECK]
                ): bool,
                vol.Optional(
                    CONF_FEATURE_RESTART_POLICY, default=defaults[CONF_FEATURE_RESTART_POLICY]
                ): bool,
                vol.Optional(
                    CONF_FEATURE_UPDATE_CHECK, default=defaults[CONF_FEATURE_UPDATE_CHECK]
                ): bool,
                vol.Optional(
                    CONF_UPDATE_CHECK_TIME, default=defaults[CONF_UPDATE_CHECK_TIME]
                ): str,
                vol.Optional(
                    CONF_CONTAINER_SENSOR_NAME_MODE,
                    default=defaults[CONF_CONTAINER_SENSOR_NAME_MODE],
                ): vol.In(list(NAME_MODE_OPTIONS.keys())),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)