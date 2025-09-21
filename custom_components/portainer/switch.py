"""Portainer switches"""
from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_CONTAINER_SENSOR_NAME_MODE,
    DEFAULT_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
    NAME_MODE_STACK_SERVICE,
)
from .coordinator import PortainerCoordinator
from .control_api import PortainerControl
from .device_ids import container_device_info, stack_device_info

_LOGGER = logging.getLogger(__name__)

_slug_invalid_re = re.compile(r"[^a-z0-9-]+")
_dash_collapse_re = re.compile(r"-{2,}")


def _slugify_stack_name(name: str) -> str:
    base = (name or "").strip().lower().replace("_", "-").replace(" ", "-")
    base = _slug_invalid_re.sub("-", base)
    base = _dash_collapse_re.sub("-", base).strip("-")
    return base or "unnamed"


def _ensure_parent_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: PortainerCoordinator,
) -> None:
    """Create endpoint & stack devices so via_device references exist for switches."""
    try:
        devreg = dr.async_get(hass)

        endpoints = coordinator.raw_data.get("endpoints", {}) or {}
        endpoint_ids = set(endpoints.keys())
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
            name = (endpoints.get(eid, {}) or {}).get("Name") or str(eid)
            devreg.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, f"endpoint_{eid}")},
                manufacturer="Portainer",
                name=f"Endpoint: {name}",
            )

        stacks_map = coordinator.raw_data.get("stacks", {}) or {}
        if not stacks_map:
            for c in (coordinator.raw_data.get("containers_by_name", {}) or {}).values():
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
            slug = _slugify_stack_name(sname)
            identifiers = {
                (DOMAIN, f"stack:{eid}:{slug}"),
                (DOMAIN, f"stack:{eid}:{sid}"),
            }
            devreg.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers=identifiers,
                manufacturer="Portainer",
                name=f"Stack: {sname}",
                via_device=(DOMAIN, f"endpoint_{eid}"),
            )
    except Exception as e:  # pragma: no cover
        _LOGGER.debug("Failed to pre-create devices: %s", e)


def _schedule_refresh_burst(hass: HomeAssistant, coordinator: PortainerCoordinator, delays=(1.0, 3.0, 7.0)) -> None:
    """Schedule several follow-up refreshes; async callbacks run on the event loop (thread-safe)."""
    for d in delays:
        async def _cb(_now, d=d):  # bind d
            await coordinator.async_request_refresh()
        async_call_later(hass, d, _cb)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    coordinator: PortainerCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    control = PortainerControl(coordinator.api)

    await coordinator.async_config_entry_first_refresh()
    _ensure_parent_devices(hass, entry, coordinator)

    containers_by_name = coordinator.raw_data.get("containers_by_name", {})
    stacks = coordinator.raw_data.get("stacks", {})

    entities: list[SwitchEntity] = []
    entities.extend(
        PortainerContainerSwitch(coordinator, control, c)
        for c in containers_by_name.values()
    )
    entities.extend(PortainerStackSwitch(coordinator, control, s) for s in stacks.values())

    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.warning("No containers/stacks found to create Portainer switches")


class PortainerContainerSwitch(CoordinatorEntity, SwitchEntity):
    """Container switch with compose-aware name + stable resolution."""

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

        self._attr_unique_id = f"{DOMAIN}_container_{self._endpoint_id}_{self._container_name}"
        self._attr_name = f"Container: {self._compute_label()}"

        self._container = container

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

    @property
    def available(self) -> bool:
        return self._resolve_current_container() is not None

    @property
    def is_on(self) -> bool:
        current = self._resolve_current_container()
        if not current:
            return False
        return str(current.get("State", "")).lower() in ("running", "restarting")

    @property
    def device_info(self):
        return container_device_info(
            self._endpoint_id,
            self._container_name,
            self._compose_stack,
            self._compose_service,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        current = self._resolve_current_container()
        if not current:
            _LOGGER.warning("Container '%s' not found on endpoint %s", self._container_name, self._endpoint_id)
            return
        await self.hass.async_add_executor_job(self._control.start_container, self._endpoint_id, current["Id"])
        await self.coordinator.async_request_refresh()
        _schedule_refresh_burst(self.hass, self.coordinator, delays=(1.0, 3.0, 7.0))  # WHY: avoid stale "running"

    async def async_turn_off(self, **kwargs: Any) -> None:
        current = self._resolve_current_container()
        if not current:
            _LOGGER.warning("Container '%s' not found on endpoint %s", self._container_name, self._endpoint_id)
            return
        await self.hass.async_add_executor_job(self._control.stop_container, self._endpoint_id, current["Id"])
        await self.coordinator.async_request_refresh()
        _schedule_refresh_burst(self.hass, self.coordinator, delays=(1.0, 3.0, 7.0))

    def _resolve_current_container(self) -> dict[str, Any] | None:
        containers_by_name = self.coordinator.raw_data.get("containers_by_name", {})
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
                        self._attr_name = f"Container: {self._compute_label()}"
                    return cand
        return None

    async def async_update(self) -> None:
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        updated = self._resolve_current_container()
        self._container = updated or {}
        self._attr_name = f"Container: {self._compute_label()}"
        super()._handle_coordinator_update()


class PortainerStackSwitch(CoordinatorEntity, SwitchEntity):
    """Stack switch (ON if any container exists for the stack)."""

    def __init__(
        self,
        coordinator: PortainerCoordinator,
        control: PortainerControl,
        stack: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._control = control
        self._stack_id = stack["Id"]  # numeric or synth-...
        self._endpoint_id: int | str = stack["EndpointId"]
        self._name: str = stack["Name"]

        self._attr_unique_id = f"{DOMAIN}_stack_{self._endpoint_id}_{self._stack_id}"
        self._attr_name = f"Stack: {self._name}"

        self._stack = stack

    @property
    def is_on(self) -> bool:
        containers_by_name = self.coordinator.raw_data.get("containers_by_name", {})
        if not containers_by_name:
            return False
        for c in containers_by_name.values():
            if c.get("EndpointId") == self._endpoint_id and c.get("Compose_Stack") == self._name:
                return True
        return False

    @property
    def device_info(self):
        return stack_device_info(self._endpoint_id, self._stack_id, self._name)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self._control.start_stack, self._endpoint_id, self._stack_id)
        await self.coordinator.async_request_refresh()
        _schedule_refresh_burst(self.hass, self.coordinator, delays=(1.0, 3.0, 7.0))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self._control.stop_stack, self._endpoint_id, self._stack_id)
        await self.coordinator.async_request_refresh()
        _schedule_refresh_burst(self.hass, self.coordinator, delays=(1.0, 3.0, 7.0))

    async def async_update(self) -> None:
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        updated = self.coordinator.raw_data["stacks"].get(f"{self._endpoint_id}:{self._stack_id}")
        if updated:
            self._stack = updated
        super()._handle_coordinator_update()
