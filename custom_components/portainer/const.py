"""Constants used by the Portainer integration."""
from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

PLATFORMS = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.SWITCH,
]

DOMAIN = "portainer"
DEFAULT_NAME = "root"
ATTRIBUTION = "Data provided by Portainer integration"

SCAN_INTERVAL = 30

DEFAULT_HOST = "10.0.0.1"

DEFAULT_DEVICE_NAME = "Portainer"
DEFAULT_SSL = False
DEFAULT_SSL_VERIFY = True

# attributes used in the entity unique_id
DEVICE_ATTRIBUTES_CONTAINERS_UNIQUE = [
    "Environment",
    "Name",
    "ConfigEntryId",
]

TO_REDACT = {
    "password",
}

CUSTOM_ATTRIBUTE_ARRAY = "_Custom"

# sensor naming mode
CONF_CONTAINER_SENSOR_NAME_MODE = "container_sensor_name_mode"

NAME_MODE_SERVICE = "service"           # prefer compose service; fallback to container name
NAME_MODE_CONTAINER = "container"       # always container name
NAME_MODE_STACK_SERVICE = "stack_service"  # compose "stack/service"; fallback to container name

DEFAULT_CONTAINER_SENSOR_NAME_MODE = NAME_MODE_SERVICE


# Stats polling options (stored in ConfigEntry.options)
CONF_STATS_SCAN_INTERVAL: str = "stats_scan_interval"
DEFAULT_STATS_SCAN_INTERVAL: int = 15  # seconds

CONF_STATS_SMOOTHING_ALPHA: str = "stats_smoothing_alpha"
DEFAULT_STATS_SMOOTHING_ALPHA: float = 0.2  # 0 disables smoothing

CONF_MEM_EXCLUDE_CACHE: str = "stats_memory_exclude_cache"
DEFAULT_MEM_EXCLUDE_CACHE: bool = True

# Stable suffixes appended to the per-container unique_id root
UNIQUE_SUFFIX_CPU_PCT: str = "cpu_pct"
UNIQUE_SUFFIX_MEM_MIB: str = "mem_mib"
UNIQUE_SUFFIX_MEM_PCT: str = "mem_pct"


# feature switch
CONF_FEATURE_HEALTH_CHECK: Final = "feature_switch_health_check"
DEFAULT_FEATURE_HEALTH_CHECK = False
CONF_FEATURE_RESTART_POLICY: Final = "feature_switch_restart_policy"
DEFAULT_FEATURE_RESTART_POLICY = False
CONF_FEATURE_UPDATE_CHECK: Final = "feature_switch_update_check"
DEFAULT_FEATURE_UPDATE_CHECK = False
CONF_UPDATE_CHECK_TIME: Final = "update_check_time"
DEFAULT_UPDATE_CHECK_TIME = "02:00"  # Default time as string HH:MM
