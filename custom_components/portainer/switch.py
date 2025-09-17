"""Portainer switches"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    # naming option
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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    coordinator: PortainerCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    control = PortainerControl(coordinator.api)

    await coordinator.async_config_entry_first_refresh()

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

        self._attr_unique_id = (
            f"{DOMAIN}_container_{self._endpoint_id}_{self._container_name}"
        )
        self._attr_name = f"Container: {self._compute_label()}"

        self._container = container

    # --- naming option helpers ---
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
        return self._container_name  # NAME_MODE_CONTAINER

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
            _LOGGER.warning(
                "Container '%s' not found on endpoint %s",
                self._container_name,
                self._endpoint_id,
            )
            return
        await self.hass.async_add_executor_job(
            self._control.start_container, self._endpoint_id, current["Id"]
        )
        await self.coordinator.async_request_refresh()
        async_call_later(
            self.hass,
            2.0,
            lambda _now: self.hass.async_create_task(
                self.coordinator.async_request_refresh()
            ),
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        current = self._resolve_current_container()
        if not current:
            _LOGGER.warning(
                "Container '%s' not found on endpoint %s",
                self._container_name,
                self._endpoint_id,
            )
            return
        await self.hass.async_add_executor_job(
            self._control.stop_container, self._endpoint_id, current["Id"]
        )
        await self.coordinator.async_request_refresh()
        async_call_later(
            self.hass,
            2.0,
            lambda _now: self.hass.async_create_task(
                self.coordinator.async_request_refresh()
            ),
        )

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
        # Recompute label in case option changed or compose labels updated
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
        self._stack_id: int = stack["Id"]
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
            if (
                c.get("EndpointId") == self._endpoint_id
                and c.get("Compose_Stack") == self._name
            ):
                return True
        return False

    @property
    def device_info(self):
        return stack_device_info(self._endpoint_id, self._stack_id, self._name)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(
            self._control.start_stack, self._endpoint_id, self._stack_id
        )
        await self.coordinator.async_request_refresh()
        async_call_later(
            self.hass,
            2.0,
            lambda _now: self.hass.async_create_task(
                self.coordinator.async_request_refresh()
            ),
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(
            self._control.stop_stack, self._endpoint_id, self._stack_id
        )
        await self.coordinator.async_request_refresh()
        async_call_later(
            self.hass,
            2.0,
            lambda _now: self.hass.async_create_task(
                self.coordinator.async_request_refresh()
            ),
        )

    async def async_update(self) -> None:
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        updated = self.coordinator.raw_data["stacks"].get(
            f"{self._endpoint_id}:{self._stack_id}"
        )
        if updated:
            self._stack = updated
        super()._handle_coordinator_update()
