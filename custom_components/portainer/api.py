"""Portainer API."""
from __future__ import annotations

from logging import getLogger
from threading import Lock, Semaphore
from typing import Any, Optional

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from requests.exceptions import (
    RequestException,
    ConnectTimeout,
    ReadTimeout,
    SSLError,
    ConnectionError as ReqConnectionError,
)
try:
    from urllib3.util.retry import Retry  # type: ignore
except Exception:  # pragma: no cover
    Retry = None  # type: ignore

from homeassistant.core import HomeAssistant

from .const import (
    HTTP_POOL_CONNECTIONS,
    HTTP_POOL_MAXSIZE,
    HTTP_CONNECT_TIMEOUT,
    HTTP_READ_TIMEOUT,
    HTTP_RETRIES_TOTAL,
    HTTP_BACKOFF_FACTOR,
    HTTP_STATUS_FORCELIST,
    STATS_MAX_CONCURRENCY,
)

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
        self._hass = hass
        self._host = host
        self._use_ssl = use_ssl
        self._api_key = api_key
        self._protocol = "https" if self._use_ssl else "http"
        # If not using SSL, keep verify True to avoid warnings from requests
        self._ssl_verify = True if not use_ssl else verify_ssl
        self._url = f"{self._protocol}://{self._host}/api/"

        self.lock = Lock()
        self._connected = False
        self._error: str = ""
        self._fail_counts: dict[str, int] = {}

        # Reusable HTTP session with larger pools + retry/backoff
        self._session: Session = requests.Session()
        try:
            retry = Retry(
                total=HTTP_RETRIES_TOTAL,
                connect=HTTP_RETRIES_TOTAL,
                read=HTTP_RETRIES_TOTAL,
                backoff_factor=HTTP_BACKOFF_FACTOR,
                status_forcelist=HTTP_STATUS_FORCELIST,
                allowed_methods=frozenset({"GET", "POST"}),
                raise_on_status=False,
            ) if Retry is not None else None
            adapter = HTTPAdapter(
                pool_connections=HTTP_POOL_CONNECTIONS,
                pool_maxsize=HTTP_POOL_MAXSIZE,
                max_retries=retry or 0,
            )
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
        except Exception:  # pragma: no cover
            pass

        # Global throttle for stats calls to reduce burstiness
        self._stats_sem = Semaphore(STATS_MAX_CONCURRENCY)

    def close(self) -> None:
        """Close underlying HTTP session (release pools/sockets)."""
        try:
            self._session.close()
        except Exception:  # pragma: no cover
            pass

    def connected(self) -> bool:
        return self._connected

    def connection_test(self) -> tuple[bool, str]:
        self.query("endpoints")
        return self._connected, self._error

    def query(
        self, service: str, method: str = "get", params: Optional[dict[str, Any]] = None
    ) -> Any | None:
        """Retrieve data from Portainer with retries + crisp error logs."""
        params = params or {}
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": f"{self._api_key}",
        }
        url = f"{self._url}{service}"

        with self.lock:
            _LOGGER.debug("Portainer %s %s %s params=%s", self._host, method.upper(), service, params)
            try:
                if method == "get":
                    resp = self._session.get(
                        url,
                        headers=headers,
                        params=params,
                        verify=self._ssl_verify,
                        timeout=(HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT),
                    )
                elif method == "post":
                    resp = self._session.post(
                        url,
                        headers=headers,
                        json=params,
                        verify=self._ssl_verify,
                        timeout=(HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT),
                    )
                else:
                    _LOGGER.warning("Unsupported HTTP method %s for %s", method, service)
                    return None
            except (ConnectTimeout, ReadTimeout) as err:
                self._record_failure(service, "timeout", detail=str(err))
                self._warn(service, "timeout", f"{type(err).__name__}")
                return None
            except SSLError as err:
                self._record_failure(service, "ssl_error", detail=str(err))
                self._warn(service, "ssl_error", f"{err}")
                return None
            except ReqConnectionError as err:
                self._record_failure(service, "connection_error", detail=str(err))
                self._warn(service, "connection_error", f"{err}")
                return None
            except RequestException as err:
                self._record_failure(service, "request_exception", detail=str(err))
                self._warn(service, "request_exception", f"{err}")
                return None
            except Exception as err:  # pragma: no cover
                self._record_failure(service, "unknown_exception", detail=str(err))
                self._warn(service, "unknown_exception", f"{err}")
                return None

            # Success
            if resp is not None and resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception as err:
                    self._record_failure(service, "invalid_json", detail=str(err))
                    self._warn(service, "invalid_json", f"{err}")
                    return None
                self._record_success(service)
                _LOGGER.debug("Portainer %s %s -> 200 OK", self._host, service)
                return data

            # Non-200
            status = getattr(resp, "status_code", None)
            reason = getattr(resp, "reason", "")
            snippet = ""
            try:
                txt = resp.text or ""
                snippet = (txt[:200] + ("..." if len(txt) > 200 else "")).replace("\n", " ")
            except Exception:
                pass
            self._record_failure(service, str(status), detail=reason)
            self._warn(service, f"http_{status}", f"{reason or 'HTTP error'} | body: {snippet}")
            return None

    def get_container_stats(self, *, endpoint_id: int | str, container_id: str) -> Any | None:
        """One-shot Docker stats. Never toggles connected state on errors."""
        service = f"endpoints/{endpoint_id}/docker/containers/{container_id}/stats"
        url = f"{self._url}{service}"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": f"{self._api_key}",
        }
        with self._stats_sem:
            try:
                resp = self._session.get(
                    url,
                    headers=headers,
                    params={"stream": "false"},
                    verify=self._ssl_verify,
                    timeout=(HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT),
                )
                if resp is not None and resp.status_code == 200:
                    return resp.json()
                _LOGGER.debug(
                    "Portainer stats non-200 for %s: %s (%s)",
                    container_id,
                    getattr(resp, "status_code", "no_response"),
                    getattr(resp, "reason", ""),
                )
                return None
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Portainer stats error for %s: %s", container_id, err)
                return None

    # ---- helpers ----
    def _record_success(self, service: str) -> None:
        self._fail_counts[service] = 0
        self._error = ""
        self._connected = True

    def _record_failure(self, service: str, code: str, *, detail: str = "") -> None:
        self._fail_counts[service] = self._fail_counts.get(service, 0) + 1
        self._error = code
        # Endpoints drives "connected" to avoid flapping on single blips
        if service == "endpoints":
            if self._fail_counts[service] >= 2:
                self._connected = False
        elif service != "reporting/get_data":
            if self._fail_counts[service] >= 2:
                self._connected = False

    def _warn(self, service: str, code: str, detail: str) -> None:
        _LOGGER.warning('Portainer %s failed "%s" [%s]: %s', self._host, service, code, detail)

    @property
    def error(self) -> str:
        return self._error
