from types import SimpleNamespace

from custom_components.portainer.switch import PortainerContainerSwitch
from custom_components.portainer.const import (
    CONF_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
    NAME_MODE_STACK_SERVICE,
)
from custom_components.portainer.device_ids import slug


class DummyControl:
    def start_container(self, endpoint_id, container_id):
        return True

    def stop_container(self, endpoint_id, container_id):
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


def build_switch(hass, container, name_mode=None):
    options = {}
    if name_mode:
        options[CONF_CONTAINER_SENSOR_NAME_MODE] = name_mode
    coord = DummyCoord({f"{container['EndpointId']}:{container['Name']}": container}, options)
    ctrl = DummyControl()
    sw = PortainerContainerSwitch(coord, ctrl, container)
    sw.hass = hass
    return sw


# --- name modes ---

def test_switch_name_service_mode(hass):
    c = mkc(1, "c1", "app", "web")
    sw = build_switch(hass, c, NAME_MODE_SERVICE)
    assert sw.name == "Container: web"


def test_switch_name_container_mode(hass):
    c = mkc(1, "c1", "app", "web")
    sw = build_switch(hass, c, NAME_MODE_CONTAINER)
    assert sw.name == "Container: c1"


def test_switch_name_stack_service_mode(hass):
    c = mkc(1, "c1", "my app", "web")
    sw = build_switch(hass, c, NAME_MODE_STACK_SERVICE)
    assert sw.name == "Container: my app/web"


def test_switch_name_service_fallback_no_compose(hass):
    c = mkc(1, "standalone")
    sw = build_switch(hass, c, NAME_MODE_SERVICE)
    assert sw.name == "Container: standalone"


# --- rename via compose fallback updates label but keeps unique_id base ---

def test_switch_rename_updates_label_keeps_unique(hass):
    initial = mkc(1, "old", "app", "web")
    coord = DummyCoord({"1:new": mkc(1, "new", "app", "web")}, {CONF_CONTAINER_SENSOR_NAME_MODE: NAME_MODE_SERVICE})
    sw = PortainerContainerSwitch(coord, DummyControl(), initial)
    sw.hass = hass

    # Before update
    assert sw.unique_id.endswith("portainer_container_1_old")

    # Coordinator update adopts new name for label computation
    sw._handle_coordinator_update()
    assert sw.name == "Container: web"
    # Unique ID remains tied to original name
    assert sw.unique_id.endswith("portainer_container_1_old")


# --- device_info basic assertions ---

def test_switch_device_info_compose(hass):
    c = mkc(1, "c1", "My App", "Web")
    sw = build_switch(hass, c, NAME_MODE_SERVICE)

    di = sw.device_info
    assert di.name == "Container: My App/Web"
    assert di.via_device == ("portainer", f"stack_name_1_{slug('My App')}")
    assert ("portainer", f"container_1_{slug('My App')}_{slug('Web')}") in di.identifiers
