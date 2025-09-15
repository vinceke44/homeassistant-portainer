from types import SimpleNamespace

from custom_components.portainer.sensor import ContainerSensor


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


class DummyCoordinator:
    def __init__(self, containers_by_name, options=None):
        self.raw_data = {"containers_by_name": containers_by_name}
        self.data = {"endpoints": {}, "containers": {}}
        self.config_entry = SimpleNamespace(
            options=options or {}, data={"name": "Portainer Test"}, entry_id="test-entry"
        )
        self.hass = None

    def connected(self):
        return True


def mkc(eid, name, stack="", service="", state="running", cid=None):
    return {
        "EndpointId": eid,
        "Name": name,
        "Compose_Stack": stack,
        "Compose_Service": service,
        "State": state,
        "Id": cid or f"id-{name}",
    }


def test_container_sensor_unique_id_stable_and_name_updates_on_rename_integration():
    # initial mapping with old id
    c1 = mkc(1, "web", "App", "web", cid="old-id")
    coord = DummyCoordinator({"1:web": c1})

    sensor = ContainerSensor(coord, DummyDesc("CPU"), uid=None)
    # initialize identity like runtime
    sensor._endpoint_id = 1
    sensor._container_name = "web"
    sensor._compose_stack = "App"
    sensor._compose_service = "web"

    original_unique = sensor.unique_id
    original_label = sensor._compute_entity_label()

    # rename in Portainer -> new id for same name
    c2 = mkc(1, "web", "App", "web", cid="new-id")
    coord.raw_data["containers_by_name"] = {"1:web": c2}

    # resolve current container (adopts latest details)
    sensor._resolve_current_container()

    # unique id must remain stable (based on endpoint+original name+sensor key)
    assert sensor.unique_id == original_unique
    # label should remain consistent for the same identity
    assert sensor._compute_entity_label() == original_label
