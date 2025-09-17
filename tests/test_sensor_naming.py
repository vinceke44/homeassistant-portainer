from types import SimpleNamespace

from custom_components.portainer.sensor import ContainerSensor
from custom_components.portainer.const import (
    CONF_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_SERVICE,
    NAME_MODE_CONTAINER,
)


class DummyDesc:
    def __init__(self, name="CPU", data_attribute="State", data_path="containers"):
        self.name = name
        self.key = name
        self.data_attribute = data_attribute
        self.data_path = data_path  # required by PortainerEntity base
        self.ha_group = ""
        self.native_unit_of_measurement = None
        self.suggested_unit_of_measurement = None
        self.icon = None  # base may access description.icon

    def __getitem__(self, k):
        return getattr(self, k)


class DummyCoordinator:
    def __init__(self, containers_by_name, options=None):
        self.raw_data = {"containers_by_name": containers_by_name}
        # Provide keys expected by PortainerEntity base
        self.data = {"endpoints": {}, "containers": {}}
        # Provide name + entry_id for base logic
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


def test_container_sensor_name_prefers_service(hass):
    # Explicitly set mode to SERVICE so label should be the compose service (Web)
    c = mkc(1, "cnt", "App", "Web")
    coord = DummyCoordinator({"1:cnt": c}, {CONF_CONTAINER_SENSOR_NAME_MODE: NAME_MODE_SERVICE})
    s = ContainerSensor(coord, DummyDesc("CPU"), uid=None)
    s.hass = hass
    # initialize identity the same way the runtime does
    s._endpoint_id = 1
    s._container_name = "cnt"
    s._compose_stack = "App"
    s._compose_service = "Web"
    assert s._compute_entity_label() == "Web"


def test_container_sensor_name_fallback_to_container_name(hass):
    # Explicitly set mode to CONTAINER so label falls back to container name
    c = mkc(1, "solo")
    coord = DummyCoordinator({"1:solo": c}, {CONF_CONTAINER_SENSOR_NAME_MODE: NAME_MODE_CONTAINER})
    s = ContainerSensor(coord, DummyDesc("CPU"), uid=None)
    s.hass = hass
    s._endpoint_id = 1
    s._container_name = "solo"
    s._compose_stack = ""
    s._compose_service = ""
    assert s._compute_entity_label() == "solo"
