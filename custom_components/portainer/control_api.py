"""Portainer Control API.

Thin, robust wrappers around Portainer actions (containers & stacks).
- Uses direct POSTs to handle 2xx (incl. 204 No Content) without depending on api.py semantics.
- Stacks use: /stacks/{stack_id}/start|stop?endpointId={endpoint_id}
"""
from __future__ import annotations

from logging import getLogger
from typing import Any

from requests import post as requests_post

from .api import PortainerAPI

_LOGGER = getLogger(__name__)


class PortainerControl:
    """Control helpers for Portainer resources."""

    def __init__(self, api: PortainerAPI) -> None:
        # Uses API's connection details; avoids API.query() to properly treat 204.
        self._url = api._url  # noqa: SLF001
        self._api_key = api._api_key  # noqa: SLF001
        self._ssl_verify = api._ssl_verify  # noqa: SLF001

    # ---------------------------
    # internals
    # ---------------------------
    def _post_action(self, service: str, body: dict[str, Any] | None = None) -> bool:
        """POST to Portainer and treat any 2xx as success.
        Why empty JSON: Portainer stack start expects a JSON payload; `{}` works.
        """
        url = f"{self._url}{service}"
        headers = {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
        }
        try:
            response = requests_post(
                url,
                headers=headers,
                json=body if body is not None else {},
                verify=self._ssl_verify,
                timeout=10,
            )
            if 200 <= response.status_code < 300:
                _LOGGER.debug("Portainer action ok: %s (status %s)", service, response.status_code)
                return True
            _LOGGER.warning(
                "Portainer action failed: %s (status %s, body=%s)",
                service,
                response.status_code,
                response.text,
            )
            return False
        except Exception as ex:  # noqa: BLE001
            _LOGGER.warning("Portainer action exception: %s (%s)", service, ex)
            return False

    # ---------------------------
    # container actions
    # ---------------------------
    def start_container(self, endpoint_id: int, container_id: str) -> bool:
        return self._post_action(
            f"endpoints/{endpoint_id}/docker/containers/{container_id}/start"
        )

    def stop_container(self, endpoint_id: int, container_id: str) -> bool:
        return self._post_action(
            f"endpoints/{endpoint_id}/docker/containers/{container_id}/stop"
        )

    def restart_container(self, endpoint_id: int, container_id: str) -> bool:
        return self._post_action(
            f"endpoints/{endpoint_id}/docker/containers/{container_id}/restart"
        )

    # ---------------------------
    # stack actions
    # ---------------------------
    def start_stack(self, endpoint_id: int, stack_id: int) -> bool:
        # Portainer requires endpointId query on /stacks
        return self._post_action(f"stacks/{stack_id}/start?endpointId={endpoint_id}")

    def stop_stack(self, endpoint_id: int, stack_id: int) -> bool:
        return self._post_action(f"stacks/{stack_id}/stop?endpointId={endpoint_id}")
