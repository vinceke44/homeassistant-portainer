import pytest
sensor.hass = hass
sensor._endpoint_id = 1
sensor._container_name = "my_container"
sensor._compose_stack = "app"
sensor._compose_service = "web"
sensor._handle_coordinator_update()


# Assert: compact name uses service, not stack or full container name
assert sensor.name == "CPU: web"




def test_container_sensor_name_fallback_to_container_name(hass):
# Arrange: container has no compose service label
container = _mk_container(1, "standalone", stack="", service="")
coord = DummyCoordinator({"1:standalone": container})
desc = DummyDesc(name="CPU", data_attribute="State")


# Act
sensor = ContainerSensor(coord, desc, uid=None)
sensor.hass = hass
sensor._endpoint_id = 1
sensor._container_name = "standalone"
sensor._compose_stack = ""
sensor._compose_service = ""
sensor._handle_coordinator_update()


# Assert: falls back to container name
assert sensor.name == "CPU: standalone"




# --- Additional tests: rename via compose fallback + device vs entity naming ---
from custom_components.portainer.device_ids import slug




def test_container_sensor_name_stable_on_rename_via_compose(hass):
"""Entity name should stay compact (service) across container rename/recreation.
Old name -> new name, same compose stack/service.
"""
# Initial entity fields
initial = _mk_container(1, "old", stack="app", service="web")
# Coordinator only knows new container name now
current = _mk_container(1, "new", stack="app", service="web")
coord = DummyCoordinator({"1:new": current})
desc = DummyDesc(name="CPU", data_attribute="State")


sensor = ContainerSensor(coord, desc, uid=None)
sensor.hass = hass
# seed identity with old values to simulate entity constructed before rename
sensor._endpoint_id = 1
sensor._container_name = "old"
sensor._compose_stack = "app"
sensor._compose_service = "web"


# Update from coordinator should adopt new container while keeping compact name (service)
sensor._handle_coordinator_update()


assert sensor.name == "CPU: web"
assert sensor._container_name == "new" # adopted new container name internally
# unique_id remains stable (based on original name + sensor key)
assert sensor.unique_id.endswith("_1_old_cpu")




def test_container_sensor_device_info_compose_vs_entity_name(hass):
"""Device and entity naming differ intentionally for UX:
- device: "Container: stack/service"
- entity: "CPU: service"
"""
container = _mk_container(1, "my_container", stack="My App", service="Web")
coord = DummyCoordinator({"1:my_container": container})
desc = DummyDesc(name="CPU", data_attribute="State")


sensor = ContainerSensor(coord, desc, uid=None)
sensor.hass = hass
sensor._endpoint_id = 1
sensor._container_name = "my_container"
sensor._compose_stack = "My App"
sensor._compose_service = "Web"
sensor._handle_coordinator_update()


# Entity name compact
assert sensor.name == "CPU: Web"


# DeviceInfo verbose and hierarchical
di = sensor.device_info
assert di.name == "Container: My App/Web"
# parent is stack by name
assert di.via_device == ("portainer", f"stack_name_1_{slug('My App')}")
# identifier is container_<endpoint>_<stack>_<service>
assert ("portainer", f"container_1_{slug('My App')}_{slug('Web')}") in di.identifiers