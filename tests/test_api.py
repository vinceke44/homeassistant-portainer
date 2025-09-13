import types
from custom_components.portainer.api import PortainerAPI

class DummyResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text or ""
        self.content = (b"{}" if payload is not None else b"")

    def json(self):
        return self._payload

def _mk_api():
    hass = types.SimpleNamespace()
    return PortainerAPI(hass, host="portainer:9443", api_key="abc", use_ssl=True, verify_ssl=False)

def test_query_200_with_json(monkeypatch):
    api = _mk_api()
    payload = {"ok": True}
    def fake_get(url, headers=None, params=None, verify=None, timeout=None):
        return DummyResponse(status=200, payload=payload)
    monkeypatch.setattr("custom_components.portainer.api.requests_get", fake_get)
    data = api.query("stacks", method="get", params={})
    assert data == payload
    assert api.connected() is True

def test_query_non_200_sets_error(monkeypatch):
    api = _mk_api()
    def fake_get(url, headers=None, params=None, verify=None, timeout=None):
        return DummyResponse(status=500, payload=None)
    monkeypatch.setattr("custom_components.portainer.api.requests_get", fake_get)
    data = api.query("stacks", method="get", params={})
    assert data is None
    assert api.connected() is False
