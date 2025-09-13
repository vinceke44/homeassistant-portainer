from types import SimpleNamespace
from custom_components.portainer.sensor import ContainerSensor
from custom_components.portainer.const import (
    CONF_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
    NAME_MODE_STACK_SERVICE,
)

class DummyDesc:
    def __init__(self, name="CPU", key="cpu", data_attribute="State", ha_group=""):
        self.name = name; self.key = key; self.data_attribute = data_attribute
        self.ha_group = ha_group; self.suggested_unit_of_measurement = None
        self.native_unit_of_measurement = None

class DummyCoord:
    def __init__(self, containers_by_name, options):
        self.raw_data = {"containers_by_name": containers_by_name}
        self.data = {"endpoints": {}}
        self.config_entry = SimpleNamespace(options=options)
    def connected(self): return True

def mkc(eid, name, stack="", service="", state="running"):
    return {"EndpointId": eid, "Name": name, "Compose_Stack": stack, "Compose_Service": service, "State": state, "Id": f"id-{name}"}

def build_sensor(hass, options, container):
    coord = DummyCoord({f"{container['EndpointId']}:{container['Name']}": container}, options)
    desc = DummyDesc()
    s = ContainerSensor(coord, desc, uid=None); s.hass = hass
    s._endpoint_id = container["EndpointId"]
    s._container_name = container["Name"]
    s._compose_stack = container["Compose_Stack"]
    s._compose_service = container["Compose_Service"]
    s._handle_coordinator_update()
    return s

def test_name_mode_service(hass):
    c = mkc(1, "c1", "app", "web")
    s = build_sensor(hass, {CONF_CONTAINER_SENSOR_NAME_MODE: NAME_MODE_SERVICE}, c)
    assert s.name == "CPU: web"

def test_name_mode_container(hass):
    c = mkc(1, "c1", "app", "web")
    s = build_sensor(hass, {CONF_CONTAINER_SENSOR_NAME_MODE: NAME_MODE_CONTAINER}, c)
    assert s.name == "CPU: c1"

def test_name_mode_stack_service(hass):
    c = mkc(1, "c1", "app", "web")
    s = build_sensor(hass, {CONF_CONTAINER_SENSOR_NAME_MODE: NAME_MODE_STACK_SERVICE}, c)
    assert s.name == "CPU: app/web"

def test_name_mode_service_fallback_no_compose(hass):
    c = mkc(1, "standalone")
    s = build_sensor(hass, {CONF_CONTAINER_SENSOR_NAME_MODE: NAME_MODE_SERVICE}, c)
    assert s.name == "CPU: standalone"
