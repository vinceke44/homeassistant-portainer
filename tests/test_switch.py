import pytest
from custom_components.portainer.switch import PortainerContainerSwitch, PortainerStackSwitch

class DummyCoord:
    def __init__(self, stacks=None, containers_by_name=None):
        self.raw_data = {"stacks": stacks or {}, "containers_by_name": containers_by_name or {}}
    async def async_request_refresh(self): pass

class DummyControl:
    def __init__(self): self.calls = []
    def start_container(self, eid, cid): self.calls.append(("start_container", eid, cid)); return True
    def stop_container(self, eid, cid): self.calls.append(("stop_container", eid, cid)); return True
    def start_stack(self, eid, sid): self.calls.append(("start_stack", eid, sid)); return True
    def stop_stack(self, eid, sid): self.calls.append(("stop_stack", eid, sid)); return True

def c(eid, name, state="running", stack="app", svc="web"):
    return {"EndpointId": eid, "Name": name, "State": state, "Compose_Stack": stack, "Compose_Service": svc, "Id": f"id-{name}"}

@pytest.fixture(autouse=True)
def patch_async_call_later(monkeypatch):
    def immediate(_hass, _delay, cb):
        try: return cb(None)
        except TypeError: return cb()
    monkeypatch.setattr("custom_components.portainer.switch.async_call_later", immediate, raising=False)
    return immediate

def test_container_switch_is_on_running(hass):
    coord = DummyCoord(containers_by_name={"1:web": c(1, "web", "running")})
    sw = PortainerContainerSwitch(coord, DummyControl(), coord.raw_data["containers_by_name"]["1:web"]); sw.hass = hass
    assert sw.is_on is True

def test_container_switch_is_off_exited(hass):
    coord = DummyCoord(containers_by_name={"1:web": c(1, "web", "exited")})
    sw = PortainerContainerSwitch(coord, DummyControl(), coord.raw_data["containers_by_name"]["1:web"]); sw.hass = hass
    assert sw.is_on is False

def test_container_switch_rename_fallback_updates_name(hass):
    initial = c(1, "oldname", "running", stack="app", svc="web")
    current = c(1, "newname", "running", stack="app", svc="web")
    coord = DummyCoord(containers_by_name={"1:newname": current})
    sw = PortainerContainerSwitch(coord, DummyControl(), initial); sw.hass = hass
    assert sw.is_on is True
    assert sw.name == "Container: newname"

@pytest.mark.asyncio
async def test_container_switch_actions_call_control(hass):
    coord = DummyCoord(containers_by_name={"1:web": c(1, "web", "running")})
    control = DummyControl()
    sw = PortainerContainerSwitch(coord, control, coord.raw_data["containers_by_name"]["1:web"]); sw.hass = hass
    await sw.async_turn_off(); await sw.async_turn_on()
    assert ("stop_container", 1, "id-web") in control.calls
    assert ("start_container", 1, "id-web") in control.calls

def test_stack_switch_is_on_if_any_container_exists(hass):
    stacks = {"1:7": {"Id": 7, "EndpointId": 1, "Name": "app"}}
    containers = {"1:a": c(1, "web", "exited", stack="app", svc="web")}
    coord = DummyCoord(stacks=stacks, containers_by_name=containers)
    sw = PortainerStackSwitch(coord, DummyControl(), stacks["1:7"]); sw.hass = hass
    assert sw.is_on is True  # exists, regardless of running

def test_stack_switch_off_when_no_containers(hass):
    stacks = {"1:7": {"Id": 7, "EndpointId": 1, "Name": "app"}}
    coord = DummyCoord(stacks=stacks, containers_by_name={})
    sw = PortainerStackSwitch(coord, DummyControl(), stacks["1:7"]); sw.hass = hass
    assert sw.is_on is False