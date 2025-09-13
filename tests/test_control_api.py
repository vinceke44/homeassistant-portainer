import types
from custom_components.portainer.api import PortainerAPI
from custom_components.portainer.control_api import PortainerControl




class DummyResponse:
def __init__(self, status=204):
self.status_code = status
self.text = ""
self.content = b""




def test_stack_start_stop_urls(monkeypatch):
seen = []


def fake_post(url, headers=None, json=None, verify=None, timeout=None):
seen.append(url)
return DummyResponse(204)


monkeypatch.setattr("custom_components.portainer.control_api.requests_post", fake_post)


api = PortainerAPI(types.SimpleNamespace(), "portainer:9443", "abc", use_ssl=True, verify_ssl=False)
ctl = PortainerControl(api)
assert ctl.start_stack(2, 7) is True
assert ctl.stop_stack(2, 7) is True


assert seen[0].endswith("/api/stacks/7/start?endpointId=2")
assert seen[1].endswith("/api/stacks/7/stop?endpointId=2")




def test_container_start_stop(monkeypatch):
seen = []


def fake_post(url, headers=None, json=None, verify=None, timeout=None):
seen.append(url)
return DummyResponse(204)


monkeypatch.setattr("custom_components.portainer.control_api.requests_post", fake_post)


api = PortainerAPI(types.SimpleNamespace(), "portainer:9443", "abc", use_ssl=True, verify_ssl=False)
ctl = PortainerControl(api)
assert ctl.start_container(1, "abc123")
assert ctl.stop_container(1, "abc123")
assert "/api/endpoints/1/docker/containers/abc123/start" in seen[0]
assert "/api/endpoints/1/docker/containers/abc123/stop" in seen[1]