"""Test control API without forcing runtime behavior changes."""
from custom_components.portainer.control_api import PortainerControl


class Resp:
    def __init__(self, status=204, text=""):
        self.status_code = status
        self.text = text


def test_container_restart_url_and_success_204(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, verify=None, timeout=None):  # noqa: A002
        captured["url"] = url
        return Resp(204)

    class DummyApi:
        _url = "http://p/api/"
        _api_key = "k"
        _ssl_verify = True

    monkeypatch.setattr(
        "custom_components.portainer.control_api.requests_post", fake_post
    )
    ctrl = PortainerControl(DummyApi())

    ok = ctrl.restart_container(1, "abc")
    assert ok is True
    assert (
        captured["url"]
        == "http://p/api/endpoints/1/docker/containers/abc/restart"
    )
