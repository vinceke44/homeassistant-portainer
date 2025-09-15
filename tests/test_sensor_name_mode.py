from types import SimpleNamespace

from custom_components.portainer.sensor import ContainerSensor
from custom_components.portainer.const import (
    CONF_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
    NAME_MODE_STACK_SERVICE,
)


class DummyDesc:
    def __init__(self, name="CPU", data_attribute="State", data_path="containers"):
        self.name = name
        self.key = name
        self.data_attribute = data_attribute
        self.data_path = data_path
        self.ha_group = ""
        self.native_unit_of_measurement = None
        self.suggested_unit_of_measurement = None
        self.icon = None

    def __getitem__(self, k):
        return getattr(self, k)


class DummyCoord:
    def __init__(self, containers_by_name, options=None):
        self.raw_data = {"containers_by_name": containers_by_name}
        self.data = {"endpoints": {}, "containers": {}}
        self.config_entry = SimpleNamespace(
            options=options or {}, data={"name": "Portainer Test"}, entry_id="test-entry"
        )
        self.hass = None

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


def _build(name_mode):
    c = mkc(1, "c1", "MyApp", "Web")
    coord = DummyCoord({"1:c1": c}, {CONF_CONTAINER_SENSOR_NAME_MODE: name_mode})
    sensor = ContainerSensor(coord, DummyDesc("CPU"), uid=None)
    # initialize identity like runtime
    sensor._endpoint_id = 1
    sensor._container_name = "c1"
    sensor._compose_stack = "MyApp"
    sensor._compose_service = "Web"
    return sensor


def test_name_mode_service():
    s = _build(NAME_MODE_SERVICE)
    assert s._compute_entity_label() == "Web"


def test_name_mode_container():
    s = _build(NAME_MODE_CONTAINER)
    assert s._compute_entity_label() == "c1"


def test_name_mode_stack_service():
    s = _build(NAME_MODE_STACK_SERVICE)
    assert s._compute_entity_label() == "MyApp/Web"


def test_name_mode_service_fallback_no_compose():
    coord = DummyCoord({"1:solo": mkc(1, "solo")}, {CONF_CONTAINER_SENSOR_NAME_MODE: NAME_MODE_SERVICE})
    s = ContainerSensor(coord, DummyDesc("CPU"), uid=None)
    s._endpoint_id = 1
    s._container_name = "solo"
    s._compose_stack = ""
    s._compose_service = ""
    assert s._compute_entity_label() == "solo"
