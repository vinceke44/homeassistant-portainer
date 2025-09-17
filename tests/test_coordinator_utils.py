from custom_components.portainer.coordinator import PortainerCoordinator

def test_index_containers_by_name_utility():
    flat_by_id = {
        "1a": {"EndpointId": 1, "Name": "web", "State": "running"},
        "1b": {"EndpointId": 1, "Name": "db", "State": "exited"},
        "2c": {"EndpointId": 2, "Name": "web", "State": "running"},
    }
    dummy_self = object()
    index = PortainerCoordinator._index_containers_by_name(dummy_self, flat_by_id)  # type: ignore[arg-type]
    assert index["1:web"]["State"] == "running"
    assert index["1:db"]["State"] == "exited"
    assert index["2:web"]["EndpointId"] == 2