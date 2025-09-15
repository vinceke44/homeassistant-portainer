from types import SimpleNamespace
import pytest

from custom_components.portainer.button import PortainerContainerRestartButton
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
        # minimal hass stub
        self.hass = SimpleNamespace(
            async_add_executor_job=lambda func, *a, **k: func(*a, **k),
            async_create_task=lambda c: None,
        )

    def connected(self):
        return True

    async def async_request_refresh(self):
        return None


class DummyControl:
    def __init__(self):
        self.calls = []

    # keep sync signature (prod code may call this in thread executor)
    def restart_container(self, endpoint_id, container_id):
        self.calls.append((endpoint_id, container_id))
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


@pytest.mark.asyncio
async def test_restart_calls_control_with_current_id_after_rename(hass):
    # initial container mapped by name
    c_old = mkc(1, "web", "MyApp", "web", cid="old-id")
    coord = DummyCoordinator({"1:web": c_old})
    ctrl = DummyControl()

    btn = PortainerContainerRestartButton(coord, ctrl, c_old)
    btn.hass = hass

    # replace the executor path with a direct call so the test works with both
    # old (awaits control) and new (executor-based) implementations
    async def fake_run_in_executor(func, *args):
        return func(*args)

    # monkeypatch instance method
    btn._run_in_executor = fake_run_in_executor  # type: ignore[attr-defined]

    # simulate rename: new container id + possibly new name
    c_new = mkc(1, "newname", "MyApp", "web", cid="new-id")
    coord.raw_data["containers_by_name"] = {"1:newname": c_new}

    # press should resolve current container and call control with new id
    await btn.async_press()

    assert ctrl.calls, "restart_container was not called"
    assert ctrl.calls[-1] == (1, "new-id")
