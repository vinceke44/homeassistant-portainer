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
    # Naming option
    CONF_CONTAINER_SENSOR_NAME_MODE,
    DEFAULT_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
    NAME_MODE_STACK_SERVICE,
    # --- Stats options ---
    CONF_STATS_SCAN_INTERVAL,
    DEFAULT_STATS_SCAN_INTERVAL,
    CONF_STATS_SMOOTHING_ALPHA,
    DEFAULT_STATS_SMOOTHING_ALPHA,
    CONF_MEM_EXCLUDE_CACHE,
    DEFAULT_MEM_EXCLUDE_CACHE,
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
            # stats
            CONF_STATS_SCAN_INTERVAL: opts.get(
                CONF_STATS_SCAN_INTERVAL, DEFAULT_STATS_SCAN_INTERVAL
            ),
            CONF_STATS_SMOOTHING_ALPHA: opts.get(
                CONF_STATS_SMOOTHING_ALPHA, DEFAULT_STATS_SMOOTHING_ALPHA
            ),
            CONF_MEM_EXCLUDE_CACHE: opts.get(
                CONF_MEM_EXCLUDE_CACHE, DEFAULT_MEM_EXCLUDE_CACHE
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
                
                vol.Optional(
                    CONF_STATS_SCAN_INTERVAL,
                    default=defaults[CONF_STATS_SCAN_INTERVAL],
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=300)),
                vol.Optional(
                    CONF_STATS_SMOOTHING_ALPHA,
                    default=defaults[CONF_STATS_SMOOTHING_ALPHA],
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                vol.Optional(
                    CONF_MEM_EXCLUDE_CACHE,
                    default=defaults[CONF_MEM_EXCLUDE_CACHE],
                ): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
