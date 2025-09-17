from __future__ import annotations

from types import SimpleNamespace

from custom_components.portainer.diagnostics import _collect_stats_diagnostics


class _DummyStatsData:
    def __init__(self) -> None:
        self.cpu_percent = 12.34567
        self.mem_used_mib = 256.789
        self.mem_percent = 25.4321
        self.raw = {
            "cpu_stats": {"a": 1},
            "precpu_stats": {"b": 2},
            "memory_stats": {"c": 3},
        }


class _DummyStatsCoordinator:
    def __init__(self) -> None:
        self.last_update_success = True
        self.data = _DummyStatsData()


def test_collect_stats_diagnostics_basic():
    # Fake hass.data namespace with one stats coordinator and minimal main coord
    entry_id = "entry123"
    container_key = "1:nginx"

    class DummyEntry:
        def __init__(self, eid: str) -> None:
            self.entry_id = eid

    class DummyMainCoord:
        def __init__(self) -> None:
            self.raw_data = {
                "endpoints": {"1": {"Name": "node1"}},
                "containers_by_name": {container_key: {"EndpointId": 1, "Name": "nginx"}},
            }

    hass = SimpleNamespace()
    hass.data = {
        "portainer": {
            entry_id: {
                "coordinator": DummyMainCoord(),
                "stats_coordinators": {container_key: _DummyStatsCoordinator()},
            }
        }
    }

    entry = DummyEntry(entry_id)
    out = _collect_stats_diagnostics(hass, entry)

    assert "endpoints_loaded" in out and out["endpoints_loaded"] == ["1"]
    assert "containers_indexed" in out and container_key in out["containers_indexed"]
    assert "stats" in out and container_key in out["stats"]

    snap = out["stats"][container_key]
    assert snap["last_update_success"] is True
    assert isinstance(snap["cpu_percent"], float)
    assert isinstance(snap["mem_used_mib"], float)
    assert isinstance(snap["mem_percent"], float)
    assert "raw_sample" in snap and "memory_stats" in snap["raw_sample"]
