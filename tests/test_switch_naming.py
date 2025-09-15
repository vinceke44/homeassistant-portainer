# file: tests/test_switch_naming.py (mode-explicit)
from types import SimpleNamespace

from custom_components.portainer.switch import PortainerContainerSwitch
from custom_components.portainer.const import (
    CONF_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
    NAME_MODE_STACK_SERVICE,
)


class DummyCoordinator:
    def __init__(self, containers_by_name, options=None):
        self.raw_data = {"containers_by_name": containers_by_name, "stacks": {}}
        self.data = {"endpoints": {}, "containers": {}}
        self.config_entry = SimpleNamespace(
            options=options or {}, data={"name": "Portainer Test"}, entry_id="test-entry"
        )
        self.hass = SimpleNamespace(async_add_executor_job=lambda f, *a, **k: None)

    def connected(self):
        return True

    async def async_request_refresh(self):
        return None


class DummyControl:
    def start_container(self, *a, **k):
        return True

    def stop_container(self, *a, **k):
        return True


def mkc(eid, name, stack="", service="", state="running"):
    return {
        "EndpointId": eid,
        "Name": name,
        "Compose_Stack": stack,
        "Compose_Service": service,
        "State": state,
        "Id": f"id-{name}",
    }


def _build_switch(name_mode):
    c = mkc(1, "c1", "MyApp", "web")
    coord = DummyCoordinator(
        {"1:c1": c}, {CONF_CONTAINER_SENSOR_NAME_MODE: name_mode}
    )
    sw = PortainerContainerSwitch(coord, DummyControl(), c)
    sw.hass = SimpleNamespace(async_add_executor_job=lambda f, *a, **k: None)
    return sw


def test_switch_name_service_mode():
    sw = _build_switch(NAME_MODE_SERVICE)
    # service label expected
    assert sw._compute_label() == "web"
    assert sw.name == "Container: web"


def test_switch_name_container_mode():
    sw = _build_switch(NAME_MODE_CONTAINER)
    assert sw._compute_label() == "c1"
    assert sw.name == "Container: c1"


def test_switch_name_stack_service_mode():
    sw = _build_switch(NAME_MODE_STACK_SERVICE)
    assert sw._compute_label() == "MyApp/web"
    assert sw.name == "Container: MyApp/web"
