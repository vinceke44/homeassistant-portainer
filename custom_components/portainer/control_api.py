"""Portainer Control API."""

from logging import getLogger
from requests import post as requests_post

from .api import PortainerAPI  

_LOGGER = getLogger(__name__)


class PortainerControl:
    """Handle control operations (containers, stacks, etc.) in Portainer."""

    def __init__(self, api: PortainerAPI) -> None:
        """Initialize the control API using the existing PortainerAPI instance."""
        self._url = api._url
        self._api_key = api._api_key
        self._ssl_verify = api._ssl_verify


    def _post_action(self, service: str) -> bool:
        """Perform a generic POST action."""
        try:
            response = requests_post(
                f"{self._url}{service}",
                headers={"X-API-Key": self._api_key},
                json={},  # Always send empty JSON body required for (start) to work
                verify=self._ssl_verify,
                timeout=10,
            )

            if response.status_code in (204, 304):
                _LOGGER.debug("Portainer action succeeded: %s", service)
                return True

            _LOGGER.warning(
                "Portainer action failed: %s (status %s, body=%s)",
                service,
                response.status_code,
                response.text,
            )
            return False

        except Exception as ex:
            _LOGGER.warning("Portainer action failed: %s (exception: %s)", service, ex)
            return False

    # ---------------------------
    #   Container actions
    # ---------------------------
    def start_container(self, endpoint_id: int, container_id: str) -> bool:
        """Start a container by ID."""
        return self._post_action(
            f"endpoints/{endpoint_id}/docker/containers/{container_id}/start"
        )

    def stop_container(self, endpoint_id: int, container_id: str) -> bool:
        """Stop a container by ID."""
        return self._post_action(
            f"endpoints/{endpoint_id}/docker/containers/{container_id}/stop"
        )

    def restart_container(self, endpoint_id: int, container_id: str) -> bool:
        """Restart a container by ID."""
        return self._post_action(
            f"endpoints/{endpoint_id}/docker/containers/{container_id}/restart"
        )

    # ---------------------------
    #   Stack actions (future)
    # ---------------------------
    def start_stack(self, endpoint_id: int, stack_id: int) -> bool:
        """Start a stack (requires Portainer Business Edition)."""
        return self._post_action(
            f"endpoints/{endpoint_id}/stacks/{stack_id}/start"
        )

    def stop_stack(self, endpoint_id: int, stack_id: int) -> bool:
        """Stop a stack (requires Portainer Business Edition)."""
        return self._post_action(
            f"endpoints/{endpoint_id}/stacks/{stack_id}/stop"
        )
