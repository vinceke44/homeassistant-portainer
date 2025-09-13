"""Portainer sensor platform."""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from logging import getLogger
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform as ep
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_FEATURE_UPDATE_CHECK,
    DEFAULT_FEATURE_UPDATE_CHECK,
    DOMAIN,
    CONF_CONTAINER_SENSOR_NAME_MODE,
    DEFAULT_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
    NAME_MODE_STACK_SERVICE,
)

from .coordinator import PortainerCoordinator
from .device_ids import container_device_info, stack_device_info
from .entity import PortainerEntity, create_sensors
from .sensor_types import SENSOR_SERVICES, SENSOR_TYPES  # noqa: F401

_LOGGER = getLogger(__name__)


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities_callback: AddEntitiesCallback,
):
    """Set up the sensor platform for a specific configuration entry."""
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

    # Detect duplicates before filtering
    entity_ids = [getattr(entity, "unique_id", None) for entity in entities]
    seen = set()
    duplicates = set()
    for eid in entity_ids:
        if eid in seen:
            duplicates.add(eid)
        else:
            seen.add(eid)
    if duplicates:
        _LOGGER.warning(
            "Duplicate entities detected during sensor setup: %s. This may indicate an issue in entity creation logic.",
            ", ".join(str(d) for d in duplicates if d is not None),
        )

    unique_entities = _filter_unique_entities(entities)
    async_add_entities_callback(unique_entities, update_before_add=True)

    # Add stack container count sensors (one per stack)
    stack_sensors = _create_stack_sensors(coordinator)
    _LOGGER.info(
        "Initial sensor setup: Added %d stack container sensors", len(stack_sensors)
    )
    if stack_sensors:
        async_add_entities_callback(stack_sensors, update_before_add=True)

    @callback
    async def async_update_controller(coordinator):
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
    }


def _register_services(hass, platform, services):
    for service in services:
        if service[0] not in hass.services.async_services().get(DOMAIN, {}):
            platform.async_register_entity_service(service[0], service[1], service[2])


def _filter_unique_entities(entities):
    unique_entities = []
    seen_unique_ids = set()
    for entity in entities:
        if hasattr(entity, "unique_id") and entity.unique_id:
            if entity.unique_id not in seen_unique_ids:
                unique_entities.append(entity)
                seen_unique_ids.add(entity.unique_id)
                _LOGGER.debug("Added entity with unique_id: %s", entity.unique_id)
            else:
                _LOGGER.warning(
                    "Removing duplicate entity with unique_id: %s (name: %s, type: %s)",
                    entity.unique_id,
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
    hass,
    config_entry,
    platform,
    coordinator,
    descriptions,
    dispatcher,
    async_add_entities_callback,
):
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)
    existing_entities_in_registry = er.async_entries_for_config_entry(
        entity_registry, config_entry.entry_id
    )
    existing_unique_ids = _get_existing_unique_ids(existing_entities_in_registry)

    platform_entities, platform_unique_ids = _get_platform_entities_and_ids(platform)
    existing_unique_ids.update(platform_unique_ids)
    _LOGGER.debug(
        "async_update_controller: registry=%d entities, platform=%d entities, total_unique_ids=%d",
        len(existing_entities_in_registry),
        len(platform_entities),
        len(existing_unique_ids),
    )

    entities = create_sensors(coordinator, descriptions, dispatcher)
    _LOGGER.debug(
        "Update controller: create_sensors returned %d entities",
        len(entities),
    )
    new_entities = _find_new_entities(entities, existing_unique_ids)

    # Also build stack container sensors (running/total) and filter new ones
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
        if new_entities:
            async_add_entities_callback(new_entities, update_before_add=True)
        if new_stack_sensors:
            _LOGGER.info("Adding %d new stack sensors", len(new_stack_sensors))
            async_add_entities_callback(new_stack_sensors, update_before_add=True)
    else:
        if new_stack_sensors:
            _LOGGER.info("Adding %d new stack sensors", len(new_stack_sensors))
            async_add_entities_callback(new_stack_sensors, update_before_add=True)
        else:
            _LOGGER.debug("No new entities to add")


def _get_existing_unique_ids(existing_entities_in_registry):
    return {
        entity.unique_id
        for entity in existing_entities_in_registry
        if entity.unique_id and entity.platform == "portainer"
    }


def _get_platform_entities_and_ids(platform):
    try:
        platform_entities = platform._entities if hasattr(platform, "_entities") else []
        platform_unique_ids = {
            entity.unique_id
            for entity in platform_entities
            if hasattr(entity, "unique_id") and entity.unique_id
        }
        return platform_entities, platform_unique_ids
    except (AttributeError, TypeError) as e:
        _LOGGER.debug("Could not access platform entities: %s", e)
        return [], set()


def _find_new_entities(entities, existing_unique_ids):
    new_entities = []
    for entity in entities:
        try:
            unique_id = entity.unique_id
            entity_name = entity.name
        except (AttributeError, TypeError, KeyError) as e:
            _LOGGER.error("Error accessing entity properties during update: %s", e)
            continue

        if not unique_id:
            _LOGGER.warning("Skipping entity with no unique_id during update")
            continue
        if not entity_name or entity_name.strip() == "":
            _LOGGER.warning(
                "Skipping entity with no name during update: unique_id=%s",
                unique_id,
            )
            continue
        if unique_id in existing_unique_ids:
            _LOGGER.debug(
                "Skipping existing entity: %s (name: %s, type: %s)",
                unique_id,
                entity_name,
                type(entity).__name__,
            )
            continue

        _LOGGER.debug("Found new entity to add: %s", unique_id)
        new_entities.append(entity)
        existing_unique_ids.add(unique_id)
    return new_entities


def _create_stack_sensors(coordinator: PortainerCoordinator):
    """Build StackContainersSensor instances for each known stack."""
    stacks = coordinator.raw_data.get("stacks", {})
    sensors = []
    for stack in stacks.values():
        try:
            sensors.append(StackContainersSensor(coordinator, stack))
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Skipping stack sensor due to error: %s", err)
    return sensors


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
        return self._data[self.description.data_attribute]

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
    """Container sensor that survives ID changes by tracking name.
    Sensor entity names are configurable: service | container | stack/service.
    """

    def __init__(self, coordinator: PortainerCoordinator, description, uid: str | None = None) -> None:
        super().__init__(coordinator, description, uid)

        # Stable identity parts
        self._endpoint_id: int | str = self._data.get("EndpointId")
        self._container_name: str = self._data.get("Name")
        self._compose_stack: str = self._data.get("Compose_Stack", "")
        self._compose_service: str = self._data.get("Compose_Service", "")

        # Unique id per sensor type; includes original container name
        sensor_key = _sensor_key_from_description(description)
        self._sensor_key = sensor_key
        self._attr_unique_id = f"{DOMAIN}_container_{self._endpoint_id}_{self._container_name}_{sensor_key}"

        # Base label from description; entity label comes from option
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
        """Read name mode from config options."""
        try:
            return self.coordinator.config_entry.options.get(
                CONF_CONTAINER_SENSOR_NAME_MODE, DEFAULT_CONTAINER_SENSOR_NAME_MODE
            )
        except Exception:
            return DEFAULT_CONTAINER_SENSOR_NAME_MODE

    def _compute_entity_label(self) -> str:
        """Make a compact, user-configurable label for sensor entity names."""
        mode = self._get_name_mode()
        service = (self._compose_service or "").strip()
        stack = (self._compose_stack or "").strip()

        if mode == NAME_MODE_SERVICE:
            return service or self._container_name
        if mode == NAME_MODE_STACK_SERVICE:
            if service and stack:
                return f"{stack}/{service}"
            return self._container_name
        # NAME_MODE_CONTAINER (default fallback)
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

        # Compose fallback: adopt new details and refresh display label if they changed
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
                    # Update name if anything relevant changed (mode may depend on stack/service)
                    if changed:
                        self._attr_name = f"{self._base_label}: {self._compute_entity_label()}"
                    return cand
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        current = self._resolve_current_container()
        self._data = current or {}
        # Re-apply naming mode in case user changed option
        self._attr_name = f"{self._base_label}: {self._compute_entity_label()}"
        self._refresh_metadata()
        super()._handle_coordinator_update()

# ---------------------------
#   StackContainersSensor
# ---------------------------
class StackContainersSensor(CoordinatorEntity, SensorEntity):
    """Sensor reporting running/total containers for a Portainer stack."""

    def __init__(self, coordinator: PortainerCoordinator, stack: dict[str, Any]):
        super().__init__(coordinator)
        self._endpoint_id: int | str = stack["EndpointId"]
        self._stack_id: int = stack["Id"]
        self._stack_name: str = stack["Name"]

        self._attr_unique_id = (
            f"{DOMAIN}_stack_containers_{self._endpoint_id}_{self._stack_id}"
        )
        self._attr_name = f"Stack Containers: {self._stack_name}"
        self._stack = stack

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
        }

    @property
    def device_info(self) -> DeviceInfo:
        # Attach to the stack device under the endpoint device
        return stack_device_info(self._endpoint_id, self._stack_id, self._stack_name)

    @callback
    def _handle_coordinator_update(self) -> None:
        updated = self.coordinator.raw_data.get("stacks", {}).get(
            f"{self._endpoint_id}:{self._stack_id}"
        )
        if updated:
            new_name = updated.get("Name", self._stack_name)
            if new_name != self._stack_name:
                self._stack_name = new_name
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
# helpers
# ---------------------------

def _sensor_key_from_description(description: Any) -> str:
    """Best-effort stable key per sensor description for unique_id purposes."""
    base = (
        getattr(description, "key", None)
        or getattr(description, "name", None)
        or getattr(description, "data_attribute", None)
        or "sensor"
    )
    return str(base).strip().lower().replace(" ", "_")
