"""Portainer switches."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback 
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PortainerCoordinator
from .control_api import PortainerControl

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up Portainer switches from a config entry."""

    coordinator: PortainerCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    control = PortainerControl(coordinator.api)

    # Ensure first data refresh is done before creating entities
    await coordinator.async_config_entry_first_refresh()

    containers = coordinator.raw_data.get("containers", {})
    _LOGGER.debug("Discovered containers for switches: %s", containers)

    entities: list[PortainerContainerSwitch] = [
        PortainerContainerSwitch(coordinator, control, container)
        for container in containers.values()
    ]

    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.warning("No containers found to create Portainer switches")


class PortainerContainerSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Portainer container as a switch."""

    def __init__(
        self,
        coordinator: PortainerCoordinator,
        control: PortainerControl,
        container: dict[str, Any],
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._control = control
        self._container_id = container["Id"]
        self._endpoint_id = container["EndpointId"]

        self._attr_unique_id = f"{DOMAIN}_container_{self._container_id}"
        self._attr_name = f"Container: {container['Name']}"

        # Keep a reference for now
        self._container = container

    @property
    def is_on(self) -> bool:
        """Return true if the container is running."""
        return self._container.get("State") == "running"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the container."""
        await self.hass.async_add_executor_job(
            self._control.start_container, self._endpoint_id, self._container_id
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the container."""
        await self.hass.async_add_executor_job(
            self._control.stop_container, self._endpoint_id, self._container_id
        )
        await self.coordinator.async_request_refresh()

    async def async_update(self) -> None:
        """Update the container state (manual refresh)."""
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update internal container reference when coordinator has new data."""
        updated = self.coordinator.raw_data["containers"].get(
            f"{self._endpoint_id}{self._container_id}"
        )
        if updated:
            self._container = updated
        super()._handle_coordinator_update()

