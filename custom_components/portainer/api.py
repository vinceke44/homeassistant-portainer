"""Portainer API."""
from __future__ import annotations

from logging import getLogger
from threading import Lock
from typing import Any

from requests import get as requests_get, post as requests_post
from requests.exceptions import (
    SSLError,
    ConnectTimeout,
    ReadTimeout,
    ConnectionError as ReqConnectionError,
    HTTPError,
    RequestException,
)

from homeassistant.core import HomeAssistant

_LOGGER = getLogger(__name__)


class PortainerAPI:
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
        # If not using SSL, verification flag is irrelevant but must be truthy for requests
        if not self._use_ssl:
            self._ssl_verify = True

        self._url = f"{self._protocol}://{self._host}/api/"
        self.lock = Lock()
        self._connected = False
        self._error: str = ""

    def connected(self) -> bool:
        """Return connected boolean."""
        return self._connected

    def connection_test(self) -> tuple[bool, str]:
        """Test connection."""
        self.query("endpoints")
        return self._connected, self._error

    def query(
        self, service: str, method: str = "get", params: dict[str, Any] | None = None
    ) -> list | dict | None:
        """Retrieve data from Portainer."""
        if params is None:
            params = {}

        self.lock.acquire()
        response = None
        data: list | dict | None = None
        error_code: str | int | None = None

        try:
            _LOGGER.debug(
                "Portainer %s query: service=%s, method=%s, params=%s",
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
            else:
                _LOGGER.warning("Unsupported HTTP method: %s", method)

            if response is not None:
                # Raise for HTTP errors (4xx/5xx) to unify handling/logging
                try:
                    response.raise_for_status()
                except HTTPError as http_err:
                    error_code = response.status_code
                    raise http_err

                data = response.json()
                _LOGGER.debug(
                    "Portainer %s query completed successfully for %s",
                    self._host,
                    service,
                )
                self._connected = True
                self._error = ""
                return data

            # Should not happen: no response object
            error_code = "no_response"
            raise RequestException("No response object returned")

        except SSLError as err:
            error_code = "ssl_error"
            self._connected = False
            _LOGGER.warning(
                "Portainer %s SSL error fetching '%s': %s (verify_ssl=%s)",
                self._host,
                service,
                err,
                self._ssl_verify,
            )
        except (ConnectTimeout, ReadTimeout) as err:
            error_code = "timeout"
            self._connected = False
            _LOGGER.warning(
                "Portainer %s timeout fetching '%s': %s", self._host, service, err
            )
        except ReqConnectionError as err:
            error_code = "conn_error"
            self._connected = False
            _LOGGER.warning(
                "Portainer %s connection error fetching '%s': %s",
                self._host,
                service,
                err,
            )
        except HTTPError as err:
            # HTTP status already captured in error_code
            self._connected = False
            status = error_code if error_code is not None else "http_error"
            _LOGGER.warning(
                "Portainer %s HTTP error fetching '%s': %s (status=%s)",
                self._host,
                service,
                err,
                status,
            )
        except RequestException as err:
            error_code = "request_error"
            self._connected = False
            _LOGGER.warning(
                "Portainer %s request error fetching '%s': %s",
                self._host,
                service,
                err,
            )
        except Exception as err:  # noqa: BLE001
            error_code = error_code or "unknown_error"
            self._connected = False
            _LOGGER.warning(
                "Portainer %s unexpected error fetching '%s': %s",
                self._host,
                service,
                err,
            )
        finally:
            # Ensure we always release the lock
            self.lock.release()

        # Normalize error_code surfaced to coordinator/diagnostics
        if response is not None and error_code is None:
            try:
                error_code = response.status_code
            except Exception:  # noqa: BLE001
                error_code = "no_response"

        self._error = str(error_code)
        return None

    @property
    def error(self) -> str:
        """Return last error code/reason."""
        return self._error
