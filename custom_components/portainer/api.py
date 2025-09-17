"""Portainer API."""

from logging import getLogger
from threading import Lock
from typing import Any

from requests import get as requests_get, post as requests_post

from homeassistant.core import HomeAssistant

_LOGGER = getLogger(__name__)


# ---------------------------
#   PortainerAPI
# ---------------------------
class PortainerAPI(object):
    """Handle all communication with Portainer."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        api_key: str,
        use_ssl: bool = False,
        verify_ssl: bool = True,
    ) -> None:
        """Initialize the Portainer API."""
        self._hass = hass
        self._host = host
        self._use_ssl = use_ssl
        self._api_key = api_key
        self._protocol = "https" if self._use_ssl else "http"
        self._ssl_verify = verify_ssl
        if not self._use_ssl:
            self._ssl_verify = True
        self._url = f"{self._protocol}://{self._host}/api/"

        self.lock = Lock()
        self._connected = False
        self._error = ""

    # ---------------------------
    #   connected
    # ---------------------------
    def connected(self) -> bool:
        """Return connected boolean."""
        return self._connected

    # ---------------------------
    #   connection_test
    # ---------------------------
    def connection_test(self) -> tuple:
        """Test connection."""
        self.query("endpoints")
        return self._connected, self._error

    # ---------------------------
    #   query
    # ---------------------------
    def query(
        self, service: str, method: str = "get", params: dict[str, Any] | None = None
    ) -> Any | None:
        """Retrieve data from Portainer."""
        if params is None:
            params = {}
        self.lock.acquire()
        error = False
        response = None
        try:
            _LOGGER.debug(
                "Portainer %s query: %s, %s, %s",
                self._host,
                service,
                method,
                params,
            )

            headers = {
                "Content-Type": "application/json",
                "X-API-Key": f"{self._api_key}",
            }
            if method == "get":
                response = requests_get(
                    f"{self._url}{service}",
                    headers=headers,
                    params=params,
                    verify=self._ssl_verify,
                    timeout=10,
                )
            elif method == "post":
                response = requests_post(
                    f"{self._url}{service}",
                    headers=headers,
                    json=params,
                    verify=self._ssl_verify,
                    timeout=10,
                )

            if response is not None and response.status_code == 200:
                data = response.json()
                _LOGGER.debug(
                    "Portainer %s query completed successfully for %s",
                    self._host,
                    service,
                )
            else:
                error = True
        except Exception:
            error = True

        if error:
            try:
                errorcode = (
                    response.status_code if response is not None else "no_response"
                )
            except Exception:
                errorcode = "no_response"

            _LOGGER.warning(
                'Portainer %s unable to fetch data "%s" (%s)',
                self._host,
                service,
                errorcode,
            )

            if errorcode != 500 and service != "reporting/get_data":
                self._connected = False

            self._error = errorcode
            self.lock.release()
            return None

        self._connected = True
        self._error = ""
        self.lock.release()

        return data

    # ---------------------------
    #   get_container_stats
    # ---------------------------
    def get_container_stats(
        self, *, endpoint_id: int | str, container_id: str
    ) -> Any | None:
        """One-shot Docker stats for a container (no stream, read-only).
        IMPORTANT: This call MUST NOT toggle global connected state on per-container errors.
        Returns JSON dict on 200, otherwise None.
        """
        service = f"endpoints/{endpoint_id}/docker/containers/{container_id}/stats"
        url = f"{self._url}{service}"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": f"{self._api_key}",
        }
        try:
            resp = requests_get(
                url,
                headers=headers,
                params={"stream": "false"},
                verify=self._ssl_verify,
                timeout=10,
            )
            if resp is not None and resp.status_code == 200:
                return resp.json()
            # Do NOT flip _connected here; per-container stats often 404/409 when stopped
            _LOGGER.debug(
                "Portainer stats non-200 for %s: %s",
                container_id,
                getattr(resp, "status_code", "no_response"),
            )
            return None
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Portainer stats error for %s: %s", container_id, err)
            return None

    @property
    def error(self):
        """Return error."""
        return self._error
