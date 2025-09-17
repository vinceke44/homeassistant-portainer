from __future__ import annotations

from types import SimpleNamespace

from custom_components.portainer.sensor import _create_stack_sensors


class DummyCoordinator:
    """Minimal coordinator stand-in for stack sensor tests."""

    def __init__(self, raw_data: dict):
        self.raw_data = raw_data
        self.config_entry = SimpleNamespace(options={})
        self._listeners = []

    # used by CoordinatorEntity
    def async_add_listener(self, update_callback):  # pragma: no cover - not needed
        self._listeners.append(update_callback)

        def _remove():
            try:
                self._listeners.remove(update_callback)
            except ValueError:
                pass

        return _remove

    async def async_request_refresh(self):  # pragma: no cover - not needed
        for cb in list(self._listeners):
            cb()

    # used by StackContainersSensor.available
    def connected(self) -> bool:
        return True


def _container(endpoint_id: int, name: str, stack: str, state: str) -> dict:
    return {
        "EndpointId": endpoint_id,
        "Name": name,
        "Compose_Stack": stack,
        "Compose_Service": name.split("_")[0],
        "Id": f"{name}-id",
        "State": state,
    }


def _mk_coordinator_with_compose_only():
    c1 = _container(1, "web_1", "myapp", "running")
    c2 = _container(1, "db_1", "myapp", "exited")
    c3 = _container(1, "cache_1", "edge", "running")

    containers_by_name = {
        f"{c['EndpointId']}:{c['Name']}": c for c in (c1, c2, c3)
    }
    # No stacks provided by API -> trigger fallback
    return DummyCoordinator({
        "containers_by_name": containers_by_name,
        "stacks": {},
    })


def test_stack_sensors_synthesized_from_compose_labels():
    coord = _mk_coordinator_with_compose_only()

    sensors = _create_stack_sensors(coord)
    # We expect two stacks: myapp, edge
    names = sorted(s.name for s in sensors)

    assert len(sensors) == 2
    assert names == ["Stack Containers: edge", "Stack Containers: myapp"]

    # Validate counts from states (myapp: 1/2; edge: 1/1)
    d = {s.name: s for s in sensors}
    assert d["Stack Containers: myapp"].native_value in ("1/2", "1/2")
    assert d["Stack Containers: edge"].native_value == "1/1"


def test_stack_sensors_use_real_stacks_when_available():
    # Provide a real stacks map; ensure fallback is not used
    stacks = {
        "1:real-1": {"Id": "real-1", "Name": "realstack", "EndpointId": 1}
    }
    coord = DummyCoordinator({
        "stacks": stacks,
        "containers_by_name": {
            "1:web_1": _container(1, "web_1", "realstack", "running")
        },
    })

    sensors = _create_stack_sensors(coord)

    assert len(sensors) == 1
    s = sensors[0]
    # Should reflect the real stack name
    assert s.name == "Stack Containers: realstack"
    # Ensure we didn't synthesize a stack id (indirectly: count still calculates)
    assert s.native_value == "1/1"
