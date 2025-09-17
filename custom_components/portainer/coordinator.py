"""Portainer coordinator with stack + stable container-name index support."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from dataclasses import dataclass
from functools import partial
from typing import Any, Dict, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_SSL,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import PortainerAPI
from .apiparser import parse_api
from .const import (
    CONF_FEATURE_HEALTH_CHECK,  # feature switch
    CONF_FEATURE_RESTART_POLICY,
    CONF_FEATURE_UPDATE_CHECK,
    CUSTOM_ATTRIBUTE_ARRAY,
    DEFAULT_FEATURE_HEALTH_CHECK,
    DEFAULT_FEATURE_RESTART_POLICY,
    DEFAULT_FEATURE_UPDATE_CHECK,
    DOMAIN,
    SCAN_INTERVAL,
    # --- stats options ---
    CONF_STATS_SCAN_INTERVAL,
    DEFAULT_STATS_SCAN_INTERVAL,
    CONF_STATS_SMOOTHING_ALPHA,
    DEFAULT_STATS_SMOOTHING_ALPHA,
    CONF_MEM_EXCLUDE_CACHE,
    DEFAULT_MEM_EXCLUDE_CACHE,
)
from .portainer_update_service import PortainerUpdateService

_LOGGER = logging.getLogger(__name__)

TRANSLATION_UPDATE_CHECK_STATUS_STATE = (
    "component.portainer.entity.sensor.update_check_status.state"
)


class PortainerCoordinator(DataUpdateCoordinator):
    """Portainer Controller Data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{config_entry.entry_id}",
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )

        self.hass = hass
        self.data = config_entry.data
        self.name = config_entry.data[CONF_NAME]
        self.host = config_entry.data[CONF_HOST]
        self.config_entry_id = config_entry.entry_id

        self.features = {
            CONF_FEATURE_HEALTH_CHECK: config_entry.options.get(
                CONF_FEATURE_HEALTH_CHECK, DEFAULT_FEATURE_HEALTH_CHECK
            ),
            CONF_FEATURE_RESTART_POLICY: config_entry.options.get(
                CONF_FEATURE_RESTART_POLICY, DEFAULT_FEATURE_RESTART_POLICY
            ),
            CONF_FEATURE_UPDATE_CHECK: config_entry.options.get(
                CONF_FEATURE_UPDATE_CHECK, DEFAULT_FEATURE_UPDATE_CHECK
            ),
        }

        self.api = PortainerAPI(
            self.hass,
            self.host,
            self.data[CONF_API_KEY],
            self.data[CONF_SSL],
            self.data[CONF_VERIFY_SSL],
        )

        self.update_service = PortainerUpdateService(
            hass, config_entry, self.api, self.features, self.config_entry_id
        )

        self.raw_data: dict[str, dict] = {
            "endpoints": {},
            "containers": {},         # flattened by container ID (legacy)
            "containers_by_name": {}, # flattened by endpoint+name
            "stacks": {},
        }

        self.lock = asyncio.Lock()
        self.config_entry = config_entry
        self._systemstats_errored: list = []
        self.datasets_hass_device_id = None

        self.config_entry.async_on_unload(self.async_shutdown)

    @property
    def update_check_time(self):
        return self.update_service.update_check_time

    async def async_update_entry(self, config_entry):
        self.config_entry = config_entry
        self.features = {
            CONF_FEATURE_HEALTH_CHECK: config_entry.options.get(
                CONF_FEATURE_HEALTH_CHECK, DEFAULT_FEATURE_HEALTH_CHECK
            ),
            CONF_FEATURE_RESTART_POLICY: config_entry.options.get(
                CONF_FEATURE_RESTART_POLICY, DEFAULT_FEATURE_RESTART_POLICY
            ),
            CONF_FEATURE_UPDATE_CHECK: config_entry.options.get(
                CONF_FEATURE_UPDATE_CHECK, DEFAULT_FEATURE_UPDATE_CHECK
            ),
        }
        await self.update_service.async_update_entry(config_entry)
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        if self.lock.locked():
            try:
                self.lock.release()
            except RuntimeError:
                pass

    def connected(self) -> bool:
        return self.api.connected()

    async def _async_update_data(self) -> dict[str, dict]:
        try:
            await asyncio.wait_for(self.lock.acquire(), timeout=10)
        except asyncio.TimeoutError:
            return {}
        try:
            self.raw_data = {}
            await self.hass.async_add_executor_job(self.get_endpoints)
            await self.hass.async_add_executor_job(self.get_containers)
            await self.hass.async_add_executor_job(self.get_stacks)
            await self.hass.async_add_executor_job(self.get_system_data)
        except Exception as error:  # noqa: BLE001
            self.lock.release()
            raise UpdateFailed(error) from error
        self.lock.release()

        _LOGGER.debug("data: %s", self.raw_data)
        async_dispatcher_send(self.hass, f"{self.config_entry.entry_id}_update", self)
        return self.raw_data

    def get_system_data(self) -> None:
        update_enabled = self.features[CONF_FEATURE_UPDATE_CHECK]
        next_update = self.get_next_update_check_time() if update_enabled else None
        if not update_enabled:
            next_update_value = "disabled"
        elif next_update:
            next_update_value = next_update.isoformat()
        else:
            next_update_value = "never"
        system_data = {
            "next_update_check": next_update_value,
            "update_feature_enabled": update_enabled,
            "last_update_check": (
                self.last_update_check.isoformat() if self.last_update_check else "never"
            ),
        }
        self.raw_data["system"] = system_data
        _LOGGER.debug("System data created: %s", system_data)

    def get_endpoints(self) -> None:
        self.raw_data["endpoints"] = parse_api(
            data={},
            source=self.api.query("endpoints"),
            key="Id",
            vals=[
                {"name": "Id", "default": 0},
                {"name": "Name", "default": "unknown"},
                {"name": "Snapshots", "default": "unknown"},
                {"name": "Type", "default": 0},
                {"name": "Status", "default": 0},
            ],
        )
        if not self.raw_data["endpoints"]:
            return
        for eid in self.raw_data["endpoints"]:
            self.raw_data["endpoints"][eid] = parse_api(
                data=self.raw_data["endpoints"][eid],
                source=self.raw_data["endpoints"][eid]["Snapshots"][0],
                vals=[
                    {"name": "DockerVersion", "default": "unknown"},
                    {"name": "Swarm", "default": False},
                    {"name": "TotalCPU", "default": 0},
                    {"name": "TotalMemory", "default": 0},
                    {"name": "RunningContainerCount", "default": 0},
                    {"name": "StoppedContainerCount", "default": 0},
                    {"name": "HealthyContainerCount", "default": 0},
                    {"name": "UnhealthyContainerCount", "default": 0},
                    {"name": "VolumeCount", "default": 0},
                    {"name": "ImageCount", "default": 0},
                    {"name": "ServiceCount", "default": 0},
                    {"name": "StackCount", "default": 0},
                    {"name": "ConfigEntryId", "default": self.config_entry_id},
                ],
            )
            del self.raw_data["endpoints"][eid]["Snapshots"]

    def get_containers(self) -> None:
        self.raw_data["containers"] = {}
        registry_checked = False

        for eid in self.raw_data["endpoints"]:
            if self.raw_data["endpoints"][eid]["Status"] != 1:
                continue
            self.raw_data["containers"][eid] = self._parse_containers_for_endpoint(eid)
            self._set_container_environment_and_config(eid)
            if self._custom_features_enabled():
                registry_checked = self._handle_custom_features_for_endpoint(
                    eid, registry_checked
                )

        # legacy: flattened by container ID
        flat_by_id = self._flatten_containers_dict_by_id(self.raw_data["containers"])
        self.raw_data["containers"] = flat_by_id

        # NEW: stable index by endpoint+name
        self.raw_data["containers_by_name"] = self._index_containers_by_name(flat_by_id)

        if registry_checked:
            self.last_update_check = dt_util.now()

    def _flatten_containers_dict_by_id(self, containers: dict) -> dict:
        """Flatten containers dict; each environment has its set of containers by ID."""
        return {
            f"{eid}{cid}": value
            for eid, t_dict in containers.items()
            for cid, value in t_dict.items()
        }

    def _index_containers_by_name(self, flat_by_id: dict) -> dict:
        """Return mapping keyed by f"{EndpointId}:{Name}" -> container dict.
        Provides a stable handle across container recreations.
        """
        index: dict[str, dict] = {}
        for c in flat_by_id.values():
            eid = c.get("EndpointId")
            name = c.get("Name")
            if eid is None or not name:
                continue
            index[f"{eid}:{name}"] = c
        return index

    def _parse_containers_for_endpoint(self, eid: str) -> dict:
        return parse_api(
            data={},
            source=self.api.query(
                f"endpoints/{eid}/docker/containers/json", "get", {"all": True}
            ),
            key="Id",
            vals=[
                {"name": "Id", "default": "unknown"},
                {"name": "Names", "default": "unknown"},
                {"name": "Image", "default": "unknown"},
                {"name": "ImageID", "default": "unknown"},
                {"name": "State", "default": "unknown"},
                {"name": "Ports", "default": "unknown"},
                {"name": "Network", "source": "HostConfig/NetworkMode", "default": "unknown"},
                {"name": "Compose_Stack", "source": "Labels/com.docker.compose.project", "default": ""},
                {"name": "Compose_Service", "source": "Labels/com.docker.compose.service", "default": ""},
                {"name": "Compose_Version", "source": "Labels/com.docker.compose.version", "default": ""},
            ],
            ensure_vals=[
                {"name": "Name", "default": "unknown"},
                {"name": "EndpointId", "default": eid},
                {"name": CUSTOM_ATTRIBUTE_ARRAY, "default": None},
            ],
        )

    def _set_container_environment_and_config(self, eid: str) -> None:
        for cid in self.raw_data["containers"][eid]:
            container = self.raw_data["containers"][eid][cid]
            container["Environment"] = self.raw_data["endpoints"][eid]["Name"]
            container["Name"] = container["Names"][0][1:]
            container["ConfigEntryId"] = self.config_entry_id
            container[CUSTOM_ATTRIBUTE_ARRAY] = {}

    def _custom_features_enabled(self) -> bool:
        return (
            self.features[CONF_FEATURE_HEALTH_CHECK]
            or self.features[CONF_FEATURE_RESTART_POLICY]
            or self.features[CONF_FEATURE_UPDATE_CHECK]
        )

    def _handle_custom_features_for_endpoint(self, eid: str, registry_checked: bool) -> bool:
        for cid in self.raw_data["containers"][eid]:
            container = self.raw_data["containers"][eid][cid]
            container[CUSTOM_ATTRIBUTE_ARRAY + "_Raw"] = parse_api(
                data={},
                source=self.api.query(
                    f"endpoints/{eid}/docker/containers/{cid}/json",
                    "get",
                    {"all": True},
                ),
                vals=[
                    {"name": "Health_Status", "source": "State/Health/Status", "default": "unknown"},
                    {"name": "Restart_Policy", "source": "HostConfig/RestartPolicy/Name", "default": "unknown"},
                ],
                ensure_vals=[
                    {"name": "Health_Status", "default": "unknown"},
                    {"name": "Restart_Policy", "default": "unknown"},
                ],
            )
            if self.features[CONF_FEATURE_HEALTH_CHECK]:
                container[CUSTOM_ATTRIBUTE_ARRAY]["Health_Status"] = container[CUSTOM_ATTRIBUTE_ARRAY + "_Raw"]["Health_Status"]
            if self.features[CONF_FEATURE_RESTART_POLICY]:
                container[CUSTOM_ATTRIBUTE_ARRAY]["Restart_Policy"] = container[CUSTOM_ATTRIBUTE_ARRAY + "_Raw"]["Restart_Policy"]
            if self.features[CONF_FEATURE_UPDATE_CHECK]:
                update_available = self.update_service.check_image_updates(eid, container)
                if update_available["registry_used"]:
                    registry_checked = True
                container[CUSTOM_ATTRIBUTE_ARRAY]["Update_Available"] = update_available["status"]
                container[CUSTOM_ATTRIBUTE_ARRAY]["Update_Description"] = update_available["status_description"]
            del container[CUSTOM_ATTRIBUTE_ARRAY + "_Raw"]
        return registry_checked

    def _get_update_description(self, status, registry_name=None, translations=None):
        desc_key = f"update_status_{status}"
        if translations is None:
            translations = getattr(self.hass, "translations", {})
        if (
            translations
            and TRANSLATION_UPDATE_CHECK_STATUS_STATE in translations
            and desc_key in translations[TRANSLATION_UPDATE_CHECK_STATUS_STATE]
        ):
            text = translations[TRANSLATION_UPDATE_CHECK_STATUS_STATE][desc_key]
            if "{registry}" in text and registry_name:  # NOSONAR
                return text.replace("{registry}", registry_name)
            return text
        default_map = {
            0: "No update available.",
            1: "Update available!",
            2: "Update status not yet checked.",
            401: "Unauthorized (registry credentials required or invalid) for registry {registry}.",
            404: "Image not found on registry ({registry}).",
            429: "Registry rate limit reached.",
            500: "Registry/internal error.",
        }
        text = default_map.get(status, f"Status code: {status}")
        if "{registry}" in text and registry_name:
            return text.replace("{registry}", registry_name)
        return text

    def should_check_updates(self) -> bool:
        return self.update_service.should_check_updates()

    async def force_update_check(self) -> None:
        _LOGGER.info("Force update check initiated for all containers")
        self.update_service.force_update_requested = True
        self.update_service.force_update_check()
        await self.async_request_refresh()
        self.update_service.force_update_requested = False
        self.last_update_check = dt_util.now()
        _LOGGER.info("Force update check completed")

    @property
    def last_update_check(self):
        return self.update_service.last_update_check

    @last_update_check.setter
    def last_update_check(self, value):
        self.update_service.last_update_check = value

    def get_next_update_check_time(self):
        return self.update_service.get_next_update_check_time()

    # ---------------------------
    # stacks
    # ---------------------------
    def get_stacks(self) -> None:
        """Fetch stacks and store in raw_data['stacks'] keyed by f"{endpoint_id}:{stack_id}"."""
        self.raw_data["stacks"] = {}
        if not self.raw_data.get("endpoints"):
            return

        stacks_map = parse_api(
            data={},
            source=self.api.query("stacks"),
            key="Id",
            vals=[
                {"name": "Id", "default": 0},
                {"name": "Name", "default": "unknown"},
                {"name": "EndpointId", "default": 0},
                {"name": "Type", "default": 0},
            ],
        )

        # If API yields nothing, build from compose labels as fallback
        if not stacks_map:
            _LOGGER.info(
                "Portainer: 'stacks' API returned no data; building synthetic stacks from compose labels"
            )
            self.raw_data["stacks"] = self._fallback_stacks_from_containers()
            return

        online_endpoints = {
            eid for eid, e in self.raw_data["endpoints"].items() if e.get("Status") == 1
        }
        grouped: dict[int | str, dict] = {}
        for sid, stack in stacks_map.items():
            eid = stack.get("EndpointId")
            if eid not in online_endpoints:
                continue
            endpoint = self.raw_data["endpoints"].get(eid)
            if not endpoint:
                continue
            stack["Environment"] = endpoint["Name"]
            stack["ConfigEntryId"] = self.config_entry_id
            grouped.setdefault(eid, {})[sid] = stack

        if not grouped:
            # All stacks filtered out -> also fallback
            self.raw_data["stacks"] = self._fallback_stacks_from_containers()
            if self.raw_data["stacks"]:
                _LOGGER.info(
                    "Portainer: built %s synthetic stacks from compose labels",
                    len(self.raw_data["stacks"]),
                )
            return

        self.raw_data["stacks"] = {
            f"{eid}:{sid}": v for eid, sd in grouped.items() for sid, v in sd.items()
        }
        _LOGGER.info(
            "Portainer: loaded %s stacks across %s endpoints",
            sum(len(v) for v in grouped.values()),
            len(grouped),
        )

    def _fallback_stacks_from_containers(self) -> dict[str, dict]:
        """Synthesize stacks from container compose labels when Portainer 'stacks' API is empty.
        Keyed as f"{EndpointId}:{synthetic_id}" with:
          - Id: 'synth-<EndpointId>:<StackName>'
          - Name: <Compose_Stack>
        """
        result: dict[str, dict] = {}
        flat = self.raw_data.get("containers", {}) or {}
        if not flat:
            return result

        for c in flat.values():
            eid = c.get("EndpointId")
            stack_name = (c.get("Compose_Stack") or "").strip()
            if not eid or not stack_name:
                continue
            synth_id = f"synth-{eid}:{stack_name}"
            key = f"{eid}:{synth_id}"
            if key in result:
                continue
            endpoint = (self.raw_data.get("endpoints") or {}).get(eid) or {}
            result[key] = {
                "Id": synth_id,
                "Name": stack_name,
                "EndpointId": eid,
                "Type": 0,
                "Environment": endpoint.get("Name", ""),
                "ConfigEntryId": self.config_entry_id,
            }

        return result


# ===================================================================
# Per-container stats coordinator (CPU% / Memory), cached by container
# ===================================================================

def _safe_get(dct: Dict[str, Any], *path: str, default: Any | None = None) -> Any:
    cur: Any = dct
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def compute_cpu_percent(stats: Dict[str, Any]) -> float:
    """Docker CPU% formula; returns 0.0 when data is insufficient."""
    cpu_total = _safe_get(stats, "cpu_stats", "cpu_usage", "total_usage", default=0) or 0
    precpu_total = _safe_get(stats, "precpu_stats", "cpu_usage", "total_usage", default=0) or 0
    system_cpu = _safe_get(stats, "cpu_stats", "system_cpu_usage", default=0) or 0
    pre_system_cpu = _safe_get(stats, "precpu_stats", "system_cpu_usage", default=0) or 0
    cpu_delta = cpu_total - precpu_total
    system_delta = system_cpu - pre_system_cpu
    if cpu_delta <= 0 or system_delta <= 0:
        return 0.0
    online_cpus = (
        _safe_get(stats, "cpu_stats", "online_cpus")
        or len(_safe_get(stats, "cpu_stats", "cpu_usage", "percpu_usage", default=[]) or [])
        or 1
    )
    return float((cpu_delta / system_delta) * online_cpus * 100.0)


def compute_memory_used_bytes(stats: Dict[str, Any], *, exclude_cache: bool = True) -> int:
    """Memory used; subtract cache/inactive_file when requested to reflect pressure."""
    usage = int(_safe_get(stats, "memory_stats", "usage", default=0) or 0)
    if not exclude_cache:
        return max(usage, 0)
    cache = int(_safe_get(stats, "memory_stats", "stats", "cache", default=0) or 0)
    if cache == 0:
        cache = int(_safe_get(stats, "memory_stats", "stats", "inactive_file", default=0) or 0)
    return max(usage - cache, 0)


def compute_memory_percent(stats: Dict[str, Any], used_bytes: int) -> float:
    limit = int(_safe_get(stats, "memory_stats", "limit", default=0) or 0)
    if limit <= 0:
        return 0.0
    return float((used_bytes / limit) * 100.0)


@dataclass(slots=True)
class ContainerStatsData:
    """Computed stats cached by the stats coordinator."""
    cpu_percent: float
    mem_used_bytes: int
    mem_used_mib: float
    mem_percent: float
    raw: Dict[str, Any]


class ContainerStatsCoordinator(DataUpdateCoordinator[ContainerStatsData]):
    """Per-container stats poller shared by three sensors.
    Keyed by a stable container key to survive renames/recreates.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        api: PortainerAPI,
        entry_id: str,
        endpoint_id: int | str,
        container_id: str,
        container_key: str,
        options: Dict[str, Any] | None = None,
    ) -> None:
        self._api = api
        self._endpoint_id = endpoint_id
        self._container_id = container_id
        self._container_key = container_key
        self._alpha: float = (options or {}).get(CONF_STATS_SMOOTHING_ALPHA, DEFAULT_STATS_SMOOTHING_ALPHA)
        self._exclude_cache: bool = (options or {}).get(CONF_MEM_EXCLUDE_CACHE, DEFAULT_MEM_EXCLUDE_CACHE)
        interval_seconds: int = int((options or {}).get(CONF_STATS_SCAN_INTERVAL, DEFAULT_STATS_SCAN_INTERVAL))
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_container_stats:{entry_id}:{container_key}",
            update_interval=timedelta(seconds=interval_seconds),
        )
        self._last_cpu: Optional[float] = None
        self._last: Optional[ContainerStatsData] = None

    async def _async_update_data(self) -> ContainerStatsData:
        # Fetch stats; None on per-container errors/stopped containers
        stats: Dict[str, Any] | None = await self.hass.async_add_executor_job(
            partial(
                self._api.get_container_stats,
                endpoint_id=self._endpoint_id,
                container_id=self._container_id,
            )
        )
        if not stats:
            # Keep last values if we have them; otherwise return zeros
            if self._last is not None:
                return self._last
            zeros = ContainerStatsData(
                cpu_percent=0.0,
                mem_used_bytes=0,
                mem_used_mib=0.0,
                mem_percent=0.0,
                raw={},
            )
            self._last = zeros
            return zeros

        cpu = compute_cpu_percent(stats)
        if self._alpha and self._alpha > 0:
            self._last_cpu = cpu if self._last_cpu is None else (self._alpha * cpu) + ((1 - self._alpha) * self._last_cpu)
            cpu_out = float(self._last_cpu)
        else:
            cpu_out = float(cpu)

        used_bytes = compute_memory_used_bytes(stats, exclude_cache=self._exclude_cache)
        mem_mib = float(used_bytes / 1048576.0)
        mem_pct = compute_memory_percent(stats, used_bytes)

        data = ContainerStatsData(
            cpu_percent=cpu_out,
            mem_used_bytes=used_bytes,
            mem_used_mib=mem_mib,
            mem_percent=mem_pct,
            raw=stats,
        )
        self._last = data
        return data


def get_or_create_container_stats_coordinator(
    hass: HomeAssistant,
    *,
    entry_id: str,
    api: PortainerAPI,
    endpoint_id: int | str,
    container_key: str,
    container_id: str,
    options: Dict[str, Any] | None,
) -> ContainerStatsCoordinator:
    """Return cached coordinator under hass.data[DOMAIN][entry_id]['stats_coordinators']."""
    registry: Dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    entry_ns: Dict[str, Any] = registry.setdefault(entry_id, {})
    stats_ns: Dict[str, Any] = entry_ns.setdefault("stats_coordinators", {})

    if container_key in stats_ns:
        coord: ContainerStatsCoordinator = stats_ns[container_key]
        # update container id on recreate/rename (keep same stable key)
        coord._container_id = container_id  # noqa: SLF001
        return coord

    coord = ContainerStatsCoordinator(
        hass,
        api=api,
        entry_id=entry_id,
        endpoint_id=endpoint_id,
        container_id=container_id,
        container_key=container_key,
        options=options or {},
    )
    stats_ns[container_key] = coord
    return coord
