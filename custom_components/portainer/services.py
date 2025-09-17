"""Portainer services registration."""

import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .control_api import PortainerControl
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONTROL: PortainerControl | None = None  # Singleton instance


async def async_register_services(hass: HomeAssistant, coordinator):
    """Register Portainer control services."""
    global CONTROL
    CONTROL = PortainerControl(coordinator.api)

    async def async_handle_container_action(call: ServiceCall):
        """Handle container actions: start, stop, restart."""
        service = call.service
        if not service.endswith("_container"):
            _LOGGER.error("Unknown service called: %s", service)
            return
    
        action = service.removesuffix("_container")  # yields "start", "stop", "restart"
    
        endpoint_id = call.data.get("endpoint_id")
        container_id = call.data.get("container_id")
        name = call.data.get("name")
    
        # Allow resolving by name
        if name and (not endpoint_id or not container_id):
            endpoint_id, container_id = _resolve_container_ids(coordinator, name)
    
        if not endpoint_id or not container_id:
            _LOGGER.error(
                "Missing identifiers for Portainer service %s. "
                "You must provide either endpoint_id+container_id or name.",
                call.service,
            )
            return
    
        _LOGGER.debug(
            "Service call portainer.%s (endpoint=%s, container=%s)",
            service,
            endpoint_id,
            container_id,
        )
    
        try:
            ok = await hass.async_add_executor_job(
                getattr(CONTROL, f"{action}_container"), endpoint_id, container_id
            )
            if ok:
                _LOGGER.info(
                    "Successfully executed %s on container=%s (endpoint=%s)",
                    action,
                    container_id,
                    endpoint_id,
                )
            else:
                _LOGGER.warning(
                    "Portainer service call failed: %s on container=%s (endpoint=%s)",
                    action,
                    container_id,
                    endpoint_id,
                )
        except Exception as err:
            _LOGGER.exception(
                "Error executing %s on container=%s (endpoint=%s): %s",
                action,
                container_id,
                endpoint_id,
                err,
            )


    def _resolve_container_ids(coordinator, name: str) -> tuple[str | None, str | None]:
        """Resolve endpoint_id and container_id from container name."""
        containers = coordinator.raw_data.get("containers", {})
        for cid, container in containers.items():
            cname = container.get("Name") or container.get("Names")
            # Handle Names as list from Docker API
            if isinstance(cname, list) and cname:
                cname = cname[0].lstrip("/")
            elif isinstance(cname, str):
                cname = cname.lstrip("/")

            if cname == name:
                return container.get("EndpointId"), container.get("Id")

        _LOGGER.error("No container found with name=%s", name)
        return None, None

    # Schema: either name OR endpoint_id+container_id
    container_action_schema = vol.Schema(
        vol.Any(
            {
                vol.Required("endpoint_id"): cv.string,
                vol.Required("container_id"): cv.string,
            },
            {
                vol.Required("name"): cv.string,
            },
        )
    )

    # Register container services
    for action in ["start", "stop", "restart"]:
        hass.services.async_register(
            DOMAIN,
            f"{action}_container",
            async_handle_container_action,
            schema=container_action_schema,
        )
