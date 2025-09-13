from custom_components.portainer.sensor import ContainerSensor, StackContainersSensor

class DummyDesc:
    def __init__(self, name="State", key="state", data_attribute="State", ha_group=""):
        self.name = name; self.key = key; self.data_attribute = data_attribute
        self.ha_group = ha_group; self.suggested_unit_of_measurement = None
        self.native_unit_of_measurement = None

class DummyCoord2:
    def __init__(self, containers_by_name, stacks=None, endpoints=None):
        self.raw_data = {"containers_by_name": containers_by_name, "stacks": stacks or {}}
        self.data = {"endpoints": endpoints or {}}
    def connected(self): return True

def test_container_sensor_unique_id_and_name_updates_on_rename(hass):
    initial = {"EndpointId": 1, "Name": "old", "Compose_Stack": "app", "Compose_Service": "web", "State": "running"}
    current = {"EndpointId": 1, "Name": "new", "Compose_Stack": "app", "Compose_Service": "web", "State": "running"}
    coord = DummyCoord2(containers_by_name={"1:new": current}, endpoints={})
    desc = DummyDesc(name="State", data_attribute="State")
    sensor = ContainerSensor(coord, desc, uid=None); sensor.hass = hass
    assert sensor.unique_id.endswith("_1_old_state")
    sensor._handle_coordinator_update()
    assert sensor.name == "State: new"

def test_stack_containers_sensor_counts(hass):
    stacks = {"1:5": {"Id": 5, "EndpointId": 1, "Name": "svc"}}
    containers = {
        "1:a": {"EndpointId": 1, "Name": "svc_1", "Compose_Stack": "svc", "State": "running"},
        "1:b": {"EndpointId": 1, "Name": "svc_2", "Compose_Stack": "svc", "State": "restarting"},
        "1:c": {"EndpointId": 1, "Name": "svc_3", "Compose_Stack": "svc", "State": "exited"},
        "1:d": {"EndpointId": 1, "Name": "other", "Compose_Stack": "other", "State": "running"},
    }
    coord = DummyCoord2(containers_by_name=containers, stacks=stacks)
    sensor = StackContainersSensor(coord, stacks["1:5"]); sensor.hass = hass
    assert sensor.native_value == "2/3"
    attrs = sensor.extra_state_attributes
    assert attrs["running"] == 2 and attrs["total"] == 3 and attrs["stopped"] == 1