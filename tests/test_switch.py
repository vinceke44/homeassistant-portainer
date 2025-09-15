from types import SimpleNamespace
import pytest

from custom_components.portainer.switch import PortainerContainerSwitch
from custom_components.portainer.const import (
    CONF_CONTAINER_SENSOR_NAME_MODE,
    NAME_MODE_CONTAINER,
)


class DummyCoordinator:
    def __init__(self, containers_by_name, options=None):
        opts = {CONF_CONTAINER_SENSOR_NAME_MODE: NAME_MODE_CONTAINER}
        if options:
            opts.update(options)
        self.raw_data = {"containers_by_name": containers_by_name}
        self.data = {"endpoints": {}, "containers": {}}
        self.config_entry = SimpleNamespace(options=opts, data={"name": "Portainer Test"}, entry_id="test-entry")
        self.hass = SimpleNamespace(async_add_executor_job=lambda func, *a, **k: func(*a, **k), async_create_task=lambda c: None)

    def connected(self):
        return True

    async def async_request_refresh(self):
        return None


class DummyControl:
    def __init__(self):
        self.calls = []

    def start_container(self, endpoint_id, container_id):
        self.calls.append(("start", endpoint_id, container_id))
        return True

    def stop_container(self, endpoint_id, container_id):
        self.calls.append(("stop", endpoint_id, container_id))
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


def test_container_switch_rename_fallback_updates_name(hass):
    c_old = mkc(1, "web", "MyApp", "web", cid="old-id")
    coord = DummyCoordinator({"1:web": c_old})
    ctrl = DummyControl()

    sw = PortainerContainerSwitch(coord, ctrl, c_old)
    sw.hass = hass
    sw.entity_id = "switch.test_switch_name"

    # New container appears with same compose identity, different name
    c_new = mkc(1, "newname", "MyApp", "web", cid="new-id")
    coord.raw_data["containers_by_name"] = {"1:newname": c_new}

    # Trigger coordinator update (entity should adopt new container name)
    sw._handle_coordinator_update()

    # In container mode, label should now be the new container name
    assert sw._compute_label() == "newname"
    assert sw.name == "Container: newname"


@pytest.mark.asyncio
async def test_container_switch_actions_call_control(hass):
    c_old = mkc(2, "api", "Svc", "api", cid="id-old")
    coord = DummyCoordinator({"2:api": c_old})
    ctrl = DummyControl()

    sw = PortainerContainerSwitch(coord, ctrl, c_old)
    sw.hass = hass  # provides async_add_executor_job
    sw.entity_id = "switch.test_switch_actions"

    # after rename, actions should use the new Id
    c_new = mkc(2, "api-renamed", "Svc", "api", cid="id-new")
    coord.raw_data["containers_by_name"] = {"2:api-renamed": c_new}

    await sw.async_turn_off()
    await sw.async_turn_on()

    assert ctrl.calls[-2:] == [("stop", 2, "id-new"), ("start", 2, "id-new")]
