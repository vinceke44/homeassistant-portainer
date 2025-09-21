"""Portainer sensor platform."""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime
from decimal import Decimal
from logging import getLogger
from typing import Any, Optional, Callable, Dict, Iterable, Set, Tuple, List

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
)
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform as ep
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.const import PERCENTAGE, UnitOfInformation

from .const import (
    CONF_FEATURE_UPDATE_CHECK,
    DEFAULT_FEATURE_UPDATE_CHECK,
    DOMAIN,
    CONF_CONTAINER_SENSOR_NAME_MODE,
    DEFAULT_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
    NAME_MODE_STACK_SERVICE,
    # --- stats config + suffixes ---
    CONF_STATS_SCAN_INTERVAL,
    DEFAULT_STATS_SCAN_INTERVAL,
    CONF_STATS_SMOOTHING_ALPHA,
    DEFAULT_STATS_SMOOTHING_ALPHA,
    CONF_MEM_EXCLUDE_CACHE,
    DEFAULT_MEM_EXCLUDE_CACHE,
    UNIQUE_SUFFIX_CPU_PCT,
    UNIQUE_SUFFIX_MEM_MIB,
    UNIQUE_SUFFIX_MEM_PCT,
)

from .coordinator import (
    PortainerCoordinator,
    ContainerStatsCoordinator,
    get_or_create_container_stats_coordinator,
)
from .device_ids import container_device_info, stack_device_info
from .entity import PortainerEntity, create_sensors
from .sensor_types import SENSOR_SERVICES, SENSOR_TYPES  # noqa: F401

_LOGGER = getLogger(__name__)

_UID_ALIASES_KEY = "_uid_aliases_global"
_CREATED_UIDS_KEY = "_created_unique_ids"


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities_callback: AddEntitiesCallback,
):
    """Set up the sensor platform for a specific configuration entry."""
    hass.data.setdefault(DOMAIN, {}).setdefault(_UID_ALIASES_KEY, set())
    hass.data.setdefault(DOMAIN, {}).setdefault(config_entry.entry_id, {})
    hass.data[DOMAIN][config_entry.entry_id].setdefault(_CREATED_UIDS_KEY, set())

    dispatcher = _get_dispatcher()
    coordinator: PortainerCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]
    platform = ep.async_get_current_platform()
    services = platform.platform.SENSOR_SERVICES
    descriptions = platform.platform.SENSOR_TYPES

    _register_services(hass, platform, services)

    entities = create_sensors(coordinator, descriptions, dispatcher)
    _LOGGER.info(
        "Initial sensor setup: Created %d entities from create_sensors",
        len(entities),
    )

    # Detect duplicates inside the batch
    seen = set()
    duplicates = set()
    for uid in (getattr(e, "unique_id", None) for e in entities):
        if not uid:
            continue
        if uid in seen:
            duplicates.add(uid)
        seen.add(uid)
    if duplicates:
        _LOGGER.warning("Duplicate entities produced by factory: %s", ", ".join(sorted(duplicates)))

    unique_entities = _filter_unique_entities(entities)

    created_uids: Set[str] = hass.data[DOMAIN][config_entry.entry_id][_CREATED_UIDS_KEY]

    # Partition
    base_entities = [e for e in unique_entities if not isinstance(e, PortainerContainerStatsSensor)]
    stats_entities = [e for e in unique_entities if isinstance(e, PortainerContainerStatsSensor)]

    # Ensure parent devices exist BEFORE adding any entities (fixes via_device warnings)
    _ensure_parent_devices(hass, config_entry, coordinator)

    # Add base entities
    for e in base_entities:
        uid = getattr(e, "unique_id", None)
        if uid:
            created_uids.add(uid)
    if base_entities:
        async_add_entities_callback(base_entities, update_before_add=True)

    # Add stats entities
    for e in stats_entities:
        uid = getattr(e, "unique_id", None)
        if uid:
            created_uids.add(uid)
    if stats_entities:
        async_add_entities_callback(stats_entities, update_before_add=False)
        try:
            await asyncio.gather(*(e.coordinator.async_request_refresh() for e in stats_entities))
        except Exception:  # pragma: no cover
            _LOGGER.debug("Could not schedule initial stats refresh for some stats sensors")

    # Stack sensors (with compose-label fallback)
    stack_sensors = _create_stack_sensors(coordinator)
    _LOGGER.info("Initial sensor setup: Added %d stack container sensors", len(stack_sensors))
    _ensure_parent_devices(hass, config_entry, coordinator)
    for e in stack_sensors:
        uid = getattr(e, "unique_id", None)
        if uid:
            created_uids.add(uid)
    if stack_sensors:
        async_add_entities_callback(stack_sensors, update_before_add=True)

    @callback
    async def async_update_controller(_coordinator):
        await _handle_update_controller(
            hass,
            config_entry,
            platform,
            coordinator,
            descriptions,
            dispatcher,
            async_add_entities_callback,
        )

    config_entry.async_on_unload(
        async_dispatcher_connect(
            hass, f"{config_entry.entry_id}_update", async_update_controller
        )
    )

    await asyncio.sleep(0)


def _get_dispatcher():
    return {
        "PortainerSensor": PortainerSensor,
        "TimestampSensor": TimestampSensor,
        "UpdateCheckSensor": UpdateCheckSensor,
        "EndpointSensor": EndpointSensor,
        "ContainerSensor": ContainerSensor,
        "ContainerStatsSensor": _container_stats_factory,
    }


def _register_services(hass, platform, services):
    for service in services:
        if service[0] not in hass.services.async_services().get(DOMAIN, {}):
            platform.async_register_entity_service(service[0], service[1], service[2])


def _filter_unique_entities(entities):
    unique_entities = []
    seen_unique_ids = set()
    for entity in entities:
        uid = getattr(entity, "unique_id", None)
        if uid:
            if uid not in seen_unique_ids:
                unique_entities.append(entity)
                seen_unique_ids.add(uid)
            else:
                _LOGGER.warning(
                    "Removing duplicate entity with unique_id: %s (name: %s, type: %s)",
                    uid,
                    getattr(entity, "name", "unknown"),
                    type(entity).__name__,
                )
        else:
            _LOGGER.warning(
                "Entity without unique_id found during setup, skipping (type: %s, name: %s)",
                type(entity).__name__,
                getattr(entity, "name", "unknown"),
            )
    return unique_entities


async def _handle_update_controller(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    platform,
    coordinator: PortainerCoordinator,
    descriptions,
    dispatcher,
    async_add_entities_callback: AddEntitiesCallback,
):
    _ensure_parent_devices(hass, config_entry, coordinator)

    platform_entities, existing_unique_ids = _collect_existing_uids(hass, config_entry, platform)
    _LOGGER.debug(
        "async_update_controller: platform=%d entities, known_unique_ids=%d",
        len(platform_entities),
        len(existing_unique_ids),
    )

    entities = create_sensors(coordinator, descriptions, dispatcher)
    new_entities = _find_new_entities(entities, existing_unique_ids)

    stack_candidates = _create_stack_sensors(coordinator)
    new_stack_sensors = _find_new_entities(stack_candidates, existing_unique_ids)

    await hass.async_add_executor_job(lambda: None)

    total_new = len(new_entities) + len(new_stack_sensors)
    if total_new:
        _LOGGER.info(
            "Adding %d new entities (%d standard, %d stack sensors)",
            total_new,
            len(new_entities),
            len(new_stack_sensors),
        )
        created_uids: Set[str] = hass.data[DOMAIN][config_entry.entry_id][_CREATED_UIDS_KEY]

        base_new = [e for e in new_entities if not isinstance(e, PortainerContainerStatsSensor)]
        stats_new = [e for e in new_entities if isinstance(e, PortainerContainerStatsSensor)]

        for e in base_new:
            uid = getattr(e, "unique_id", None)
            if uid:
                created_uids.add(uid)
        if base_new:
            async_add_entities_callback(base_new, update_before_add=True)

        for e in stats_new:
            uid = getattr(e, "unique_id", None)
            if uid:
                created_uids.add(uid)
        if stats_new:
            async_add_entities_callback(stats_new, update_before_add=False)
            try:
                await asyncio.gather(*(e.coordinator.async_request_refresh() for e in stats_new))
            except Exception:  # pragma: no cover
                _LOGGER.debug("Could not schedule initial stats refresh for some stats sensors")

        if new_stack_sensors:
            for e in new_stack_sensors:
                uid = getattr(e, "unique_id", None)
                if uid:
                    created_uids.add(uid)
            _ensure_parent_devices(hass, config_entry, coordinator)
            async_add_entities_callback(new_stack_sensors, update_before_add=True)
    else:
        _LOGGER.debug("No new entities to add")


def _collect_existing_uids(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    platform,
) -> Tuple[list, Set[str]]:
    platform_entities = platform._entities if hasattr(platform, "_entities") else []
    platform_uids: Set[str] = {e.unique_id for e in platform_entities if getattr(e, "unique_id", None)}

    registry = er.async_get(hass)
    registry_uids: Set[str] = set()
    for entry in list(registry.entities.values()):
        try:
            if (
                entry.platform == DOMAIN
                and entry.config_entry_id == config_entry.entry_id
                and entry.domain == "sensor"
                and entry.unique_id
            ):
                registry_uids.add(entry.unique_id)
        except Exception:
            continue

    created_uids: Set[str] = set(hass.data[DOMAIN][config_entry.entry_id].get(_CREATED_UIDS_KEY, set()))
    alias_uids: Set[str] = set(hass.data.get(DOMAIN, {}).get(_UID_ALIASES_KEY, set()))

    known: Set[str] = platform_uids | registry_uids | created_uids | alias_uids
    return platform_entities, known


def _find_new_entities(entities, existing_unique_ids: Set[str]):
    new_entities = []
    for entity in entities:
        try:
            unique_id = getattr(entity, "unique_id", None)
            entity_name = getattr(entity, "name", None)
        except Exception as e:
            _LOGGER.error("Error accessing entity properties during update: %s", e)
            continue

        if not unique_id:
            _LOGGER.warning("Skipping entity with no unique_id during update")
            continue
        if not entity_name or not str(entity_name).strip():
            _LOGGER.warning("Skipping entity with no name during update: unique_id=%s", unique_id)
            continue
        if unique_id in existing_unique_ids:
            _LOGGER.debug("Skipping already-known entity: %s (%s)", unique_id, type(entity).__name__)
            continue

        new_entities.append(entity)
        existing_unique_ids.add(unique_id)

    return new_entities


def _create_stack_sensors(coordinator: PortainerCoordinator):
    """Build StackContainersSensor instances for each known stack."""
    stacks_map: Dict[str, dict] = coordinator.raw_data.get("stacks", {}) or {}

    if not stacks_map:
        containers_by_name = coordinator.raw_data.get("containers_by_name", {}) or {}
        synth: Dict[str, dict] = {}
        for c in containers_by_name.values():
            eid = c.get("EndpointId")
            stack_name = (c.get("Compose_Stack") or "").strip()
            if not eid or not stack_name:
                continue
            synth_id = f"synth-{eid}:{stack_name}"
            key = f"{eid}:{synth_id}"
            if key not in synth:
                synth[key] = {"Id": synth_id, "Name": stack_name, "EndpointId": eid}
        if synth:
            _LOGGER.info("Synthesized %d stacks from compose labels", len(synth))
        stacks_map = synth

    sensors = []
    for stack in stacks_map.values():
        try:
            sensors.append(StackContainersSensor(coordinator, stack))
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Skipping stack sensor due to error: %s", err)
    return sensors


# ---------------------------
#   Devices pre-creation
# ---------------------------
def _ensure_parent_devices(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    coordinator: PortainerCoordinator,
) -> None:
    """Create endpoint & stack devices so via_device references always exist."""
    try:
        devreg = dr.async_get(hass)

        # Endpoints
        endpoints_map: Dict[Any, Dict[str, Any]] = coordinator.raw_data.get("endpoints", {}) or {}
        endpoint_ids: Set[Any] = set(endpoints_map.keys())
        if not endpoint_ids:
            for c in (coordinator.raw_data.get("containers_by_name", {}) or {}).values():
                eid = c.get("EndpointId")
                if eid is not None:
                    endpoint_ids.add(eid)
            for s in (coordinator.raw_data.get("stacks", {}) or {}).values():
                eid = s.get("EndpointId")
                if eid is not None:
                    endpoint_ids.add(eid)

        for eid in endpoint_ids:
            name = (endpoints_map.get(eid, {}) or {}).get("Name") or str(eid)
            devreg.async_get_or_create(
                config_entry_id=config_entry.entry_id,
                identifiers={(DOMAIN, f"endpoint_{eid}")},
                manufacturer="Portainer",
                name=f"Endpoint: {name}",
            )

        # Stacks (real or synth) as children of endpoints
        stacks_map: Dict[str, dict] = coordinator.raw_data.get("stacks", {}) or {}
        if not stacks_map:
            containers_by_name = coordinator.raw_data.get("containers_by_name", {}) or {}
            for c in containers_by_name.values():
                eid = c.get("EndpointId")
                stack_name = (c.get("Compose_Stack") or "").strip()
                if not eid or not stack_name:
                    continue
                sid = f"synth-{eid}:{stack_name}"
                key = f"{eid}:{sid}"
                stacks_map[key] = {"Id": sid, "Name": stack_name, "EndpointId": eid}

        for stack in stacks_map.values():
            endpoint_id = stack.get("EndpointId")
            sid = str(stack.get("Id"))
            name = stack.get("Name") or sid
            sslug = _slugify_stack_name(name).replace("-", "_")  # align with device_ids.slug style if needed
            identifiers = {
                (DOMAIN, f"stack_{endpoint_id}_{sslug}"),         # canonical by name
                (DOMAIN, f"stack_{endpoint_id}_{sid}"),           # legacy by id
                (DOMAIN, f"stack_name_{endpoint_id}_{sslug}"),    # legacy alias
            }
            devreg.async_get_or_create(
                config_entry_id=config_entry.entry_id,
                identifiers=identifiers,
                manufacturer="Portainer",
                name=f"Stack: {name}",
                via_device=(DOMAIN, f"endpoint_{endpoint_id}"),
            )
    except Exception as e:  # pragma: no cover
        _LOGGER.debug("Failed to pre-create devices: %s", e)


# ---------------------------
#   PortainerSensor
# ---------------------------
class PortainerSensor(PortainerEntity, SensorEntity):
    """Define an Portainer sensor."""

    def __init__(
        self,
        coordinator: PortainerCoordinator,
        description,
        uid: str | None = None,
    ):
        super().__init__(coordinator, description, uid)
        self._attr_suggested_unit_of_measurement = (
            self.description.suggested_unit_of_measurement
        )

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        # Avoid KeyError when underlying data disappears mid-session
        try:
            return self._data.get(self.description.data_attribute)  # type: ignore[return-value]
        except Exception:
            return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.description.native_unit_of_measurement:
            if self.description.native_unit_of_measurement.startswith("data__"):
                uom = self.description.native_unit_of_measurement[6:]
                if uom in self._data:
                    return self._data[uom]
            return self.description.native_unit_of_measurement

    @property
    def entity_registry_enabled_default(self) -> bool:
        return True


# ---------------------------
#   TimestampSensor
# ---------------------------
class TimestampSensor(PortainerSensor):
    """Sensor that handles timestamp values."""

    def __init__(
        self,
        coordinator: PortainerCoordinator,
        description,
        uid: str | None = None,
    ):
        super().__init__(coordinator, description, uid)
        self._attr_device_class = "timestamp"

    @property
    def available(self) -> bool:
        return self.coordinator.connected()

    @property
    def native_value(self) -> datetime | str | None:
        if not hasattr(self, "_data") or not self._data:
            return "never"
        value = self._data.get(self.description.data_attribute)
        if value and isinstance(value, str):
            if value in ["disabled", "never"]:
                return value
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                return "never"
        return "never"

    @property
    def device_class(self) -> str | None:
        if not hasattr(self, "_data") or not self._data:
            return None
        value = self._data.get(self.description.data_attribute)
        if value and isinstance(value, str) and value not in ["disabled", "never"]:
            return "timestamp"
        return None

    @property
    def extra_state_attributes(self) -> dict:
        attrs = super().extra_state_attributes or {}
        if not hasattr(self, "_data") or not self._data:
            return attrs
        value = self._data.get(self.description.data_attribute)
        if value in ["disabled", "never"]:
            attrs["status"] = value
        return attrs


# ---------------------------
#   EndpointSensor
# ---------------------------
class EndpointSensor(PortainerSensor):
    """Define an Portainer sensor."""

    def __init__(
        self,
        coordinator: PortainerCoordinator,
        description,
        uid: str | None = None,
    ):
        super().__init__(coordinator, description, uid)
        self.manufacturer = "Portainer"


# ---------------------------
#   ContainerSensor
# ---------------------------
class ContainerSensor(PortainerSensor):
    """Container sensor that survives ID changes by tracking name."""

    def __init__(self, coordinator: PortainerCoordinator, description, uid: str | None = None) -> None:
        super().__init__(coordinator, description, uid)

        self._endpoint_id: int | str = self._data.get("EndpointId")
        self._container_name: str = self._data.get("Name")
        self._compose_stack: str = self._data.get("Compose_Stack", "")
        self._compose_service: str = self._data.get("Compose_Service", "")

        sensor_key = _sensor_key_from_description(description)
        self._sensor_key = sensor_key
        self._attr_unique_id = f"{DOMAIN}_container_{self._endpoint_id}_{self._container_name}_{sensor_key}"

        self._base_label = (
            getattr(self.description, "name", None)
            or getattr(self.description, "key", None)
            or getattr(self.description, "data_attribute", None)
            or "Container"
        )
        self._attr_name = f"{self._base_label}: {self._compute_entity_label()}"

        self._refresh_metadata()

        if getattr(self.description, "ha_group", "").startswith("data__"):
            dev_group = self.description.ha_group[6:]
            if (dev_group in self._data and self._data[dev_group] in self.coordinator.data.get("endpoints", {})):
                self.description.ha_group = self.coordinator.data["endpoints"][self._data[dev_group]]["Name"]

    def _get_name_mode(self) -> str:
        try:
            return self.coordinator.config_entry.options.get(
                CONF_CONTAINER_SENSOR_NAME_MODE, DEFAULT_CONTAINER_SENSOR_NAME_MODE
            )
        except Exception:
            return DEFAULT_CONTAINER_SENSOR_NAME_MODE

    def _compute_entity_label(self) -> str:
        mode = self._get_name_mode()
        service = (self._compose_service or "").strip()
        stack = (self._compose_stack or "").strip()

        if mode == NAME_MODE_SERVICE:
            return service or self._container_name
        if mode == NAME_MODE_STACK_SERVICE:
            if service and stack:
                return f"{stack}/{service}"
            return self._container_name
        return self._container_name

    @property
    def available(self) -> bool:
        return self._resolve_current_container() is not None

    @property
    def device_info(self) -> DeviceInfo:
        return container_device_info(
            self._endpoint_id,
            self._container_name,
            self._compose_stack,
            self._compose_service,
        )

    def _refresh_metadata(self) -> None:
        try:
            self.sw_version = self.coordinator.data["endpoints"][self._endpoint_id]["DockerVersion"]
        except Exception:  # noqa: BLE001
            self.sw_version = None

    def _resolve_current_container(self) -> dict[str, Any] | None:
        key = f"{self._endpoint_id}:{self._container_name}"
        containers_by_name = self.coordinator.raw_data.get("containers_by_name", {})
        found = containers_by_name.get(key)
        if found:
            return found

        if self._compose_stack or self._compose_service:
            for cand in containers_by_name.values():
                if (
                    cand.get("EndpointId") == self._endpoint_id
                    and cand.get("Compose_Stack") == self._compose_stack
                    and cand.get("Compose_Service") == self._compose_service
                ):
                    new_name = cand.get("Name") or self._container_name
                    changed = new_name != self._container_name
                    self._container_name = new_name
                    if changed:
                        self._attr_name = f"{self._base_label}: {self._compute_entity_label()}"
                    return cand
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        current = self._resolve_current_container()
        self._data = current or {}
        self._attr_name = f"{self._base_label}: {self._compute_entity_label()}"
        self._refresh_metadata()
        super()._handle_coordinator_update()


# ---------------------------
#   StackContainersSensor
# ---------------------------
class StackContainersSensor(CoordinatorEntity, SensorEntity):
    """Sensor reporting running/total containers for a Portainer stack."""

    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: PortainerCoordinator, stack: dict[str, Any]):
        super().__init__(coordinator)
        self._endpoint_id: int | str = stack["EndpointId"]
        self._stack_id: str = str(stack["Id"])  # may be numeric or synth-...
        self._stack_name: str = stack["Name"]
        self._stack_slug: str = _slugify_stack_name(self._stack_name)

        canonical_uid = f"{DOMAIN}_stack_containers_{self._endpoint_id}_{self._stack_slug}"
        legacy_uid = f"{DOMAIN}_stack_containers_{self._endpoint_id}_{self._stack_id}"

        ent_reg = er.async_get(coordinator.hass)
        adopted_legacy = False
        if ent_reg.async_get_entity_id("sensor", DOMAIN, legacy_uid):
            self._attr_unique_id = legacy_uid
            adopted_legacy = True
            coordinator.hass.data[DOMAIN][_UID_ALIASES_KEY].add(canonical_uid)
            _LOGGER.debug("Adopting legacy UID for stack '%s' (endpoint=%s): %s", self._stack_name, self._endpoint_id, legacy_uid)
        else:
            self._attr_unique_id = canonical_uid

        self._attr_name = f"Stack Containers: {self._stack_name}"
        self._stack = stack
        self._adopted_legacy = adopted_legacy
        self._canonical_uid = canonical_uid
        self._legacy_uid = legacy_uid

    @property
    def available(self) -> bool:
        return self.coordinator.connected()

    def _counts(self) -> tuple[int, int]:
        containers_by_name = self.coordinator.raw_data.get("containers_by_name", {})
        relevant = [
            c
            for c in containers_by_name.values()
            if c.get("EndpointId") == self._endpoint_id
            and c.get("Compose_Stack") == self._stack_name
        ]
        total = len(relevant)
        running = sum(
            1
            for c in relevant
            if str(c.get("State", "")).lower() in ("running", "restarting")
        )
        return running, total

    @property
    def native_value(self) -> str:
        running, total = self._counts()
        return f"{running}/{total}"

    @property
    def extra_state_attributes(self) -> dict:
        running, total = self._counts()
        return {
            "running": running,
            "total": total,
            "stopped": max(total - running, 0),
            "endpoint_id": self._endpoint_id,
            "stack_id": self._stack_id,
            "stack_slug": self._stack_slug,
            "uid_canonical": self._canonical_uid,
            "uid_legacy": self._legacy_uid,
            "uid_adopted_legacy": self._adopted_legacy,
        }

    @property
    def device_info(self) -> DeviceInfo:
        # Device identifiers now come from device_ids; already includes canonical+legacy
        return stack_device_info(self._endpoint_id, self._stack_id, self._stack_name)

    @callback
    def _handle_coordinator_update(self) -> None:
        updated = (self.coordinator.raw_data.get("stacks", {}) or {}).get(
            f"{self._endpoint_id}:{self._stack_id}"
        )
        if updated:
            new_name = updated.get("Name", self._stack_name)
            if new_name != self._stack_name and new_name:
                self._stack_name = new_name
                self._stack_slug = _slugify_stack_name(self._stack_name)
                self._attr_name = f"Stack Containers: {self._stack_name}"
            self._stack = updated
        super()._handle_coordinator_update()


# ---------------------------
#   UpdateCheckSensor
# ---------------------------
class UpdateCheckSensor(PortainerSensor):
    """Single sensor for update check status across all containers."""

    def __init__(
        self,
        coordinator: PortainerCoordinator,
        description,
        uid: str | None = None,
    ):
        super().__init__(coordinator, description, uid)
        self._attr_icon = "mdi:clock-outline"
        self.manufacturer = "Portainer"

        feature_enabled = coordinator.config_entry.options.get(
            CONF_FEATURE_UPDATE_CHECK, DEFAULT_FEATURE_UPDATE_CHECK
        )
        feature_enabled = feature_enabled is True
        self._attr_entity_registry_enabled_default = feature_enabled

        _LOGGER.debug(
            "Update Check Sensor initialized: feature_enabled=%s, entity_enabled_default=%s",
            feature_enabled,
            self._attr_entity_registry_enabled_default,
        )

    @property
    def entity_registry_enabled_default(self) -> bool:
        if hasattr(self, "_attr_entity_registry_enabled_default"):
            return self._attr_entity_registry_enabled_default
        feature_enabled = self.coordinator.config_entry.options.get(
            CONF_FEATURE_UPDATE_CHECK, DEFAULT_FEATURE_UPDATE_CHECK
        )
        return feature_enabled is True

    @property
    def available(self) -> bool:
        feature_enabled = self.coordinator.config_entry.options.get(
            CONF_FEATURE_UPDATE_CHECK, DEFAULT_FEATURE_UPDATE_CHECK
        )
        feature_enabled = feature_enabled is True
        coordinator_connected = self.coordinator.connected()
        return feature_enabled and coordinator_connected

    def _get_time_until_text(self, target_datetime: datetime) -> str:
        from datetime import timezone

        now = datetime.now(timezone.utc)
        if target_datetime.tzinfo is None:
            target_datetime = target_datetime.replace(tzinfo=timezone.utc)
        time_diff = target_datetime - now
        if time_diff.total_seconds() < 0:
            return "Overdue"
        hours = int(time_diff.total_seconds() // 3600)
        minutes = int((time_diff.total_seconds() % 3600) // 60)
        if hours > 0:
            return f"in {hours} hour{'s' if hours != 1 else ''}"
        if minutes > 0:
            return f"in {minutes} minute{'s' if minutes != 1 else ''}"
        return "in less than a minute"

    @property
    def native_value(self) -> str | datetime | None:
        try:
            feature_enabled = self.coordinator.config_entry.options.get(
                CONF_FEATURE_UPDATE_CHECK, DEFAULT_FEATURE_UPDATE_CHECK
            )
            feature_enabled = feature_enabled is True
            if not feature_enabled:
                return "disabled"
            next_update = self.coordinator.get_next_update_check_time()
            if next_update:
                return dt_util.as_local(next_update)
            return "never"
        except (KeyError, AttributeError, TypeError):
            return "never"

    @property
    def name(self) -> str:
        return "Container Update Check"

    @property
    def device_class(self) -> str | None:
        value = self.native_value
        if isinstance(value, datetime):
            return "timestamp"
        return None

    @property
    def extra_state_attributes(self) -> dict:
        attrs = super().extra_state_attributes or {}
        try:
            update_enabled = self.coordinator.config_entry.options.get(
                CONF_FEATURE_UPDATE_CHECK, DEFAULT_FEATURE_UPDATE_CHECK
            )
            update_enabled = update_enabled is True
            attrs["update_feature_enabled"] = update_enabled

            value = self.native_value
            if isinstance(value, datetime):
                attrs["time_until_check"] = self._get_time_until_text(value)
                local_dt = dt_util.as_local(value)
                attrs["next_check_time"] = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            elif value == "disabled":
                attrs["status_text"] = "Update check is disabled"
            elif value == "never":
                attrs["status_text"] = "Update check has never been scheduled"

            if "system" in self.coordinator.data:
                system_data = self.coordinator.data["system"]
                attrs["last_update_check"] = system_data.get("last_update_check", "never")

            if "containers" in self.coordinator.data:
                attrs["total_containers"] = len(self.coordinator.data["containers"])
        except (KeyError, AttributeError, TypeError):
            pass
        return attrs

    async def async_update_entry(self, config_entry):
        self.coordinator.config_entry = config_entry
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
        self.async_schedule_update_ha_state()


# ---------------------------
#   Stats sensors (CPU% / Memory): entity + factory
# ---------------------------

_ATTR_BY_SUFFIX: dict[str, str] = {
    UNIQUE_SUFFIX_CPU_PCT: "cpu_percent",
    UNIQUE_SUFFIX_MEM_MIB: "mem_used_mib",
    UNIQUE_SUFFIX_MEM_PCT: "mem_percent",
}


class PortainerContainerStatsSensor(CoordinatorEntity[ContainerStatsCoordinator], SensorEntity):
    """Per-container CPU/Mem sensor backed by a shared stats coordinator."""

    _attr_has_entity_name = False

    def __init__(
        self,
        *,
        coordinator: ContainerStatsCoordinator,
        metric_suffix: str,
        endpoint_id: int | str,
        container_name: str,
        compose_stack: str,
        compose_service: str,
        name_mode: str,
        state_getter: Optional[Callable[[], Any]] = None,
        icon: Optional[str] = None,
    ) -> None:
        super().__init__(coordinator)

        sensor_key = _sensor_key_for_suffix(metric_suffix)
        self._attr_unique_id = f"{DOMAIN}_container_{endpoint_id}_{container_name}_{sensor_key}"

        base_label = _label_for_suffix(metric_suffix)
        entity_label = _compute_entity_label_for(
            container_name=container_name,
            compose_stack=compose_stack,
            compose_service=compose_service,
            name_mode=name_mode,
        )
        self._attr_name = f"{base_label}: {entity_label}"

        self._endpoint_id = endpoint_id
        self._container_name = container_name
        self._compose_stack = compose_stack
        self._compose_service = compose_service

        self._attr_state_class = SensorStateClass.MEASUREMENT
        if metric_suffix == UNIQUE_SUFFIX_CPU_PCT:
            self._attr_device_class = SensorDeviceClass.POWER_FACTOR
            self._attr_native_unit_of_measurement = PERCENTAGE
        elif metric_suffix == UNIQUE_SUFFIX_MEM_MIB:
            self._attr_device_class = SensorDeviceClass.DATA_SIZE
            self._attr_native_unit_of_measurement = UnitOfInformation.MEBIBYTES
        else:
            self._attr_device_class = SensorDeviceClass.POWER_FACTOR
            self._attr_native_unit_of_measurement = PERCENTAGE

        if icon:
            self._attr_icon = icon
        elif metric_suffix == UNIQUE_SUFFIX_CPU_PCT:
            self._attr_icon = "mdi:cpu-64-bit"
        else:
            self._attr_icon = "mdi:memory"

        self._metric_attr = _ATTR_BY_SUFFIX[metric_suffix]
        self._state_getter = state_getter

    @property
    def available(self) -> bool:
        try:
            if self._state_getter is not None:
                state = self._state_getter()
                return str(state).lower() in ("running", "restarting")
            return super().available
        except Exception:  # pragma: no cover
            return super().available

    @property
    def native_value(self) -> float | int | None:
        data = self.coordinator.data
        if not data:
            return None
        value = getattr(data, self._metric_attr, None)
        if self._metric_attr == "mem_used_mib" and isinstance(value, float):
            return round(value, 2)
        if isinstance(value, float):
            return round(value, 3)
        return value

    @property
    def device_info(self) -> DeviceInfo:
        return container_device_info(
            self._endpoint_id,
            self._container_name,
            self._compose_stack,
            self._compose_service,
        )


def _container_stats_factory(
    coordinator: PortainerCoordinator,
    description: Any,
    uid: str | None = None,
):
    """Dispatcher factory: create one stats sensor for a container."""
    try:
        if uid is None:
            return None
        cont: dict[str, Any] = coordinator.raw_data["containers"][uid]
    except Exception:
        return None

    endpoint_id = cont.get("EndpointId")
    container_name = cont.get("Name")
    container_id = cont.get("Id") or uid
    compose_stack = cont.get("Compose_Stack", "")
    compose_service = cont.get("Compose_Service", "")

    opts = coordinator.config_entry.options or {}
    options = {
        CONF_STATS_SCAN_INTERVAL: opts.get(CONF_STATS_SCAN_INTERVAL, DEFAULT_STATS_SCAN_INTERVAL),
        CONF_STATS_SMOOTHING_ALPHA: opts.get(CONF_STATS_SMOOTHING_ALPHA, DEFAULT_STATS_SMOOTHING_ALPHA),
        CONF_MEM_EXCLUDE_CACHE: opts.get(CONF_MEM_EXCLUDE_CACHE, DEFAULT_MEM_EXCLUDE_CACHE),
    }

    entry_id = coordinator.config_entry.entry_id
    container_key = f"{endpoint_id}:{container_name}"
    stats_coord: ContainerStatsCoordinator = get_or_create_container_stats_coordinator(
        hass=coordinator.hass,
        entry_id=entry_id,
        api=coordinator.api,
        endpoint_id=endpoint_id,
        container_key=container_key,
        container_id=container_id,
        options=options,
    )

    key = getattr(description, "key", "") or ""
    if key.endswith(UNIQUE_SUFFIX_CPU_PCT):
        suffix = UNIQUE_SUFFIX_CPU_PCT
    elif key.endswith(UNIQUE_SUFFIX_MEM_MIB):
        suffix = UNIQUE_SUFFIX_MEM_MIB
    else:
        suffix = UNIQUE_SUFFIX_MEM_PCT

    name_mode = opts.get(CONF_CONTAINER_SENSOR_NAME_MODE, DEFAULT_CONTAINER_SENSOR_NAME_MODE)

    def _state_getter() -> Any:
        key2 = f"{endpoint_id}:{container_name}"
        return (coordinator.raw_data.get("containers_by_name", {}) or {}).get(key2, {}).get("State")

    return PortainerContainerStatsSensor(
        coordinator=stats_coord,
        metric_suffix=suffix,
        endpoint_id=endpoint_id,
        container_name=container_name,
        compose_stack=compose_stack,
        compose_service=compose_service,
        name_mode=name_mode,
        state_getter=_state_getter,
        icon=getattr(description, "icon", None),
    )


def _label_for_suffix(suffix: str) -> str:
    if suffix == UNIQUE_SUFFIX_CPU_PCT:
        return "CPU Usage (%)"
    if suffix == UNIQUE_SUFFIX_MEM_MIB:
        return "Memory Used (MiB)"
    return "Memory Usage (%)"


def _sensor_key_for_suffix(suffix: str) -> str:
    return {
        UNIQUE_SUFFIX_CPU_PCT: "containers_cpu_pct",
        UNIQUE_SUFFIX_MEM_MIB: "containers_mem_mib",
        UNIQUE_SUFFIX_MEM_PCT: "containers_mem_pct",
    }.get(suffix, suffix)


def _compute_entity_label_for(
    *,
    container_name: str,
    compose_stack: str,
    compose_service: str,
    name_mode: str,
) -> str:
    service = (compose_service or "").strip()
    stack = (compose_stack or "").strip()

    if name_mode == NAME_MODE_SERVICE:
        return service or container_name
    if name_mode == NAME_MODE_STACK_SERVICE:
        if service and stack:
            return f"{stack}/{service}"
        return container_name
    return container_name


# ---------------------------
# helpers
# ---------------------------
def _sensor_key_from_description(description: Any) -> str:
    base = (
        getattr(description, "key", None)
        or getattr(description, "name", None)
        or getattr(description, "data_attribute", None)
        or "sensor"
    )
    return str(base).strip().lower().replace(" ", "_")


_slug_invalid_re = re.compile(r"[^a-z0-9-]+")
_dash_collapse_re = re.compile(r"-{2,}")


def _slugify_stack_name(name: str) -> str:
    base = (name or "").strip().lower().replace("_", "-").replace(" ", "-")
    base = _slug_invalid_re.sub("-", base)
    base = _dash_collapse_re.sub("-", base).strip("-")
    return base or "unnamed"
