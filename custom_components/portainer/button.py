"""Portainer button platform."""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, List, Set

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr 
import re
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_FEATURE_UPDATE_CHECK,
    DEFAULT_FEATURE_UPDATE_CHECK,
    DOMAIN,
    # naming option shared with sensors
    CONF_CONTAINER_SENSOR_NAME_MODE,
    DEFAULT_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
    NAME_MODE_STACK_SERVICE,
)
from .coordinator import PortainerCoordinator
from .control_api import PortainerControl
from .device_ids import container_device_info

_LOGGER = logging.getLogger(__name__)

# --- helpers for stack ids (keep legacy alias to satisfy existing via_device) ---
_slug_invalid_re = re.compile(r"[^a-z0-9-]+")
_dash_collapse_re = re.compile(r"-{2,}")

def _slugify_stack_name(name: str) -> str:
    base = (name or "").strip().lower().replace("_", "-").replace(" ", "-")
    base = _slug_invalid_re.sub("-", base)
    base = _dash_collapse_re.sub("-", base).strip("-")
    return base or "unnamed"

def _ensure_parent_devices(hass: HomeAssistant, entry: ConfigEntry, coord: PortainerCoordinator) -> None:
    """Create endpoint & stack devices so via_device targets exist before adding entities."""
    try:
        devreg = dr.async_get(hass)

        # Endpoints
        endpoints = coord.raw_data.get("endpoints", {}) or {}
        endpoint_ids = set(endpoints.keys())
        if not endpoint_ids:
            for c in (coord.raw_data.get("containers_by_name", {}) or {}).values():
                eid = c.get("EndpointId")
                if eid is not None:
                    endpoint_ids.add(eid)
            for s in (coord.raw_data.get("stacks", {}) or {}).values():
                eid = s.get("EndpointId")
                if eid is not None:
                    endpoint_ids.add(eid)
        for eid in endpoint_ids:
            name = (endpoints.get(eid, {}) or {}).get("Name") or str(eid)
            devreg.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, f"endpoint_{eid}")},
                manufacturer="Portainer",
                name=f"Endpoint: {name}",
            )

        # Stacks (canonical underscore scheme + legacy aliases)
        stacks_map = coord.raw_data.get("stacks", {}) or {}
        if not stacks_map:
            for c in (coord.raw_data.get("containers_by_name", {}) or {}).values():
                eid = c.get("EndpointId")
                sname = (c.get("Compose_Stack") or "").strip()
                if not eid or not sname:
                    continue
                sid = f"synth-{eid}:{sname}"
                stacks_map[f"{eid}:{sid}"] = {"Id": sid, "Name": sname, "EndpointId": eid}

        for stack in stacks_map.values():
            eid = stack.get("EndpointId")
            sid = str(stack.get("Id"))
            sname = stack.get("Name") or sid
            sslug = _slugify_stack_name(sname).replace("-", "_")
            identifiers = {
                (DOMAIN, f"stack_{eid}_{sslug}"),         # canonical (by name)
                (DOMAIN, f"stack_{eid}_{sid}"),           # legacy (by id)
                (DOMAIN, f"stack_name_{eid}_{sslug}"),    # legacy alias
            }
            devreg.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers=identifiers,
                manufacturer="Portainer",
                name=f"Stack: {sname}",
                via_device=(DOMAIN, f"endpoint_{eid}"),
            )
    except Exception as e:  # pragma: no cover
        _LOGGER.debug("Failed to pre-create devices (button): %s", e)


async def async_setup_entry(  # NOSONAR
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up the button platform."""
    coordinator: PortainerCoordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    control = PortainerControl(coordinator.api)

    # Make sure coordinator has data first (so we can pre-create devices correctly)
    await coordinator.async_config_entry_first_refresh()
    _ensure_parent_devices(hass, config_entry, coordinator)

    # Force Update Check button (always)
    base_entities: list[ButtonEntity] = [ForceUpdateCheckButton(coordinator, config_entry.entry_id)]
    async_add_entities(base_entities, update_before_add=False)

    # Helper to build restart buttons for all known containers
    def _build_restart_buttons() -> List[ButtonEntity]:
        buttons: list[ButtonEntity] = []
        containers_by_name = coordinator.raw_data.get("containers_by_name", {}) or {}
        for c in containers_by_name.values():
            try:
                buttons.append(PortainerContainerRestartButton(coordinator, control, c))
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Skipping restart button for container due to error: %s", err)
        return buttons

    # Initial pass: add any restart buttons now
    restart_now = _build_restart_buttons()
    if restart_now:
        async_add_entities(restart_now, update_before_add=False)
        _LOGGER.info("Added %d container restart buttons (initial)", len(restart_now))

    # Keep track of what we’ve created (unique_ids) to avoid duplicates
    created: Set[str] = {e.unique_id for e in base_entities + restart_now if e.unique_id}

    @callback
    async def _async_update_controller(_coordinator):
        """Dynamically add buttons for newly discovered containers."""
        # Ensure parents exist for any new stacks/endpoints before adding entities
        _ensure_parent_devices(hass, config_entry, coordinator)

        new_buttons: list[ButtonEntity] = []
        containers_by_name = coordinator.raw_data.get("containers_by_name", {}) or {}
        for c in containers_by_name.values():
            uid = f"{DOMAIN}_container_restart_{c.get('EndpointId')}_{c.get('Name')}"
            if not uid or uid in created:
                continue
            try:
                btn = PortainerContainerRestartButton(coordinator, control, c)
                new_buttons.append(btn)
                created.add(uid)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Skipping new restart button due to error: %s", err)

        if new_buttons:
            async_add_entities(new_buttons, update_before_add=False)
            _LOGGER.info("Added %d new container restart buttons", len(new_buttons))

    # Listen for coordinator refreshes to add new buttons later
    config_entry.async_on_unload(
        async_dispatcher_connect(hass, f"{config_entry.entry_id}_update", _async_update_controller)
    )

    # Ensure we run at least once after setup (in case first refresh beat us)
    await _async_update_controller(coordinator)


class ForceUpdateCheckButton(ButtonEntity):
    """Button to force immediate update check."""

    _attr_should_poll = False

    def __init__(self, coordinator: PortainerCoordinator, entry_id: str) -> None:
        self.coordinator = coordinator
        self.entry_id = entry_id

        self._attr_name = "Force Update Check"
        self._attr_icon = "mdi:update"
        self._attr_unique_id = f"{entry_id}_force_update_check_final"

        feature_enabled = coordinator.config_entry.options.get(
            CONF_FEATURE_UPDATE_CHECK, DEFAULT_FEATURE_UPDATE_CHECK
        )
        feature_enabled = feature_enabled is True
        self._attr_entity_registry_enabled_default = feature_enabled

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.name}_System_{self.entry_id}")},
            "name": f"{self.coordinator.name} System",
            "manufacturer": "Portainer",
        }

    @property
    def available(self) -> bool:
        feature_enabled = self.coordinator.config_entry.options.get(
            CONF_FEATURE_UPDATE_CHECK, DEFAULT_FEATURE_UPDATE_CHECK
        )
        feature_enabled = feature_enabled is True
        return feature_enabled and (
            self.coordinator.connected() or getattr(self.coordinator, "last_update_success", False)
        )

    @property
    def entity_registry_enabled_default(self) -> bool:
        feature_enabled = self.coordinator.config_entry.options.get(
            CONF_FEATURE_UPDATE_CHECK, DEFAULT_FEATURE_UPDATE_CHECK
        )
        feature_enabled = feature_enabled is True
        return feature_enabled

    async def async_press(self) -> None:
        _LOGGER.info("Force Update Check button pressed")
        await self.coordinator.force_update_check()

    async def async_update_entry(self, config_entry):
        self.coordinator.config_entry = config_entry
        self.async_write_ha_state()


class PortainerContainerRestartButton(CoordinatorEntity, ButtonEntity):
    """Restart button for a container (compose-aware, stable-by-name)."""

    _attr_should_poll = False

    def __init__(
        self,
        coordinator: PortainerCoordinator,
        control: PortainerControl,
        container: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._control = control

        self._endpoint_id: int | str = container["EndpointId"]
        self._container_name: str = container["Name"]
        self._compose_stack: str = container.get("Compose_Stack", "")
        self._compose_service: str = container.get("Compose_Service", "")

        self._attr_unique_id = f"{DOMAIN}_container_restart_{self._endpoint_id}_{self._container_name}"
        self._attr_icon = "mdi:restart"
        self._attr_name = f"Restart: {self._compute_label()}"

        self._container = container

    @property
    def available(self) -> bool:
        return self._resolve_current_container() is not None

    @property
    def device_info(self):
        return container_device_info(
            self._endpoint_id,
            self._container_name,
            self._compose_stack,
            self._compose_service,
        )

    # naming mode
    def _get_name_mode(self) -> str:
        try:
            return self.coordinator.config_entry.options.get(
                CONF_CONTAINER_SENSOR_NAME_MODE, DEFAULT_CONTAINER_SENSOR_NAME_MODE
            )
        except Exception:
            return DEFAULT_CONTAINER_SENSOR_NAME_MODE

    def _compute_label(self) -> str:
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

    def _resolve_current_container(self) -> dict[str, Any] | None:
        containers_by_name = self.coordinator.raw_data.get("containers_by_name", {}) or {}
        key = f"{self._endpoint_id}:{self._container_name}"
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
                    new_name = cand.get("Name")
                    if new_name and new_name != self._container_name:
                        self._container_name = new_name
                        self._attr_name = f"Restart: {self._compute_label()}"
                    return cand
        return None

    async def async_press(self) -> None:
        current = self._resolve_current_container()
        if not current:
            _LOGGER.warning(
                "Restart pressed but container '%s' not found on endpoint %s",
                self._container_name,
                self._endpoint_id,
            )
            return

        await self.hass.async_add_executor_job(
            self._control.restart_container, self._endpoint_id, current["Id"]
        )
        # Immediate refresh, then a delayed refresh via async callback (thread-safe)
        await self.coordinator.async_request_refresh()

        async def _refresh_later(_now) -> None:  # runs on event loop
            await self.coordinator.async_request_refresh()

        async_call_later(self.hass, 2.0, _refresh_later)

    @callback
    def _handle_coordinator_update(self) -> None:
        updated = self._resolve_current_container()
        self._container = updated or {}
        self._attr_name = f"Restart: {self._compute_label()}"
        super()._handle_coordinator_update()
