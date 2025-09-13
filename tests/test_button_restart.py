import pytest

from types import SimpleNamespace

from custom_components.portainer.button import PortainerContainerRestartButton
from custom_components.portainer.const import (
    CONF_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
    NAME_MODE_STACK_SERVICE,
)
from custom_components.portainer.device_ids import slug


class DummyControl:
    def __init__(self):
        self.calls = []

    def restart_container(self, endpoint_id, container_id):
        self.calls.append(("restart", endpoint_id, container_id))
        return True


class DummyCoord:
    def __init__(self, containers_by_name, options=None):
        self.raw_data = {"containers_by_name": containers_by_name}
        self.data = {"endpoints": {}}
        self.config_entry = SimpleNamespace(options=options or {})

    def connected(self):
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


@pytest.fixture(autouse=True)
def patch_async_call_later(monkeypatch):
    # make delayed refresh immediate for deterministic tests
    def immediate(_hass, _delay, cb):
        try:
            return cb(None)
        except TypeError:
            return cb()
    monkeypatch.setattr(
        "custom_components.portainer.button.async_call_later",
        immediate,
        raising=False,
    )
    return immediate


def build_button(hass, container, name_mode=None):
    options = {}
    if name_mode:
        options[CONF_CONTAINER_SENSOR_NAME_MODE] = name_mode
    coord = DummyCoord({f"{container['EndpointId']}:{container['Name']}": container}, options)
    ctrl = DummyControl()
    btn = PortainerContainerRestartButton(coord, ctrl, container)
    btn.hass = hass
    return btn, ctrl


# --- label modes ---

def test_restart_button_label_service_mode(hass):
    c = mkc(1, "c1", "app", "web")
    btn, _ = build_button(hass, c, NAME_MODE_SERVICE)
    assert btn.name == "Restart: web"


def test_restart_button_label_container_mode(hass):
    c = mkc(1, "c1", "app", "web")
    btn, _ = build_button(hass, c, NAME_MODE_CONTAINER)
    assert btn.name == "Restart: c1"


def test_restart_button_label_stack_service_mode(hass):
    c = mkc(1, "c1", "my app", "web")
    btn, _ = build_button(hass, c, NAME_MODE_STACK_SERVICE)
    assert btn.name == "Restart: my app/web"


def test_restart_button_label_service_fallback_no_compose(hass):
    c = mkc(1, "standalone")
    btn, _ = build_button(hass, c, NAME_MODE_SERVICE)
    assert btn.name == "Restart: standalone"


# --- press/restart semantics ---
@pytest.mark.asyncio
async def test_restart_calls_control_with_current_id_after_rename(hass):
    # initial entity constructed with old name; coordinator knows only new name/id
    initial = mkc(1, "old", "app", "web", state="running")
    current = mkc(1, "new", "app", "web", state="running")
    current["Id"] = "id-new"

    coord = DummyCoord({"1:new": current}, {CONF_CONTAINER_SENSOR_NAME_MODE: NAME_MODE_SERVICE})
    ctrl = DummyControl()
    btn = PortainerContainerRestartButton(coord, ctrl, initial)
    btn.hass = hass

    # update adopts the new container name via compose fallback
    btn._handle_coordinator_update()
    assert btn.available is True
    assert btn.name == "Restart: web"

    await btn.async_press()

    assert ("restart", 1, "id-new") in ctrl.calls


# --- device hierarchy assertions ---

def test_restart_button_device_info_compose(hass):
    c = mkc(1, "c1", "My App", "Web")
    btn, _ = build_button(hass, c, NAME_MODE_SERVICE)

    di = btn.device_info
    # Container device uses descriptive name
    assert di.name == "Container: My App/Web"
    # parent is stack by name
    assert di.via_device == ("portainer", f"stack_name_1_{slug('My App')}")
    # identifier contains container endpoint + stack/service
    assert ("portainer", f"container_1_{slug('My App')}_{slug('Web')}") in di.identifiers


def test_restart_button_availability_false_when_missing(hass):
    # coordinator has no matching container
    coord = DummyCoord({}, {})
    ctrl = DummyControl()
    initial = mkc(1, "ghost", "", "")
    btn = PortainerContainerRestartButton(coord, ctrl, initial)
    btn.hass = hass
    assert btn.available is False
