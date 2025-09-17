# tests/test_stats_calculation.py
from __future__ import annotations

import math
import pytest

# Import the calculation helpers from the integration
from custom_components.portainer.coordinator import (
    compute_cpu_percent,
    compute_memory_used_bytes,
    compute_memory_percent,
)


@pytest.fixture
def stats_payload():
    """Minimal Docker stats payload to validate formulas.

    cpu_total delta = 100_000_000
    system_cpu delta = 500_000_000
    online_cpus = 4
    => CPU% = (100M / 500M) * 4 * 100 = 80.0

    memory usage = 500_000_000
    cache = 100_000_000
    limit = 2_000_000_000
    => used (exclude cache) = 400_000_000 bytes; percent = 20.0
    """
    return {
        "cpu_stats": {
            "cpu_usage": {
                "total_usage": 1_100_000_000,
                "percpu_usage": [1, 2, 3, 4],
            },
            "system_cpu_usage": 2_500_000_000,
            "online_cpus": 4,
        },
        "precpu_stats": {
            "cpu_usage": {
                "total_usage": 1_000_000_000,
            },
            "system_cpu_usage": 2_000_000_000,
        },
        "memory_stats": {
            "usage": 500_000_000,
            "stats": {
                "cache": 100_000_000,
                "inactive_file": 0,
            },
            "limit": 2_000_000_000,
        },
    }


def test_compute_cpu_percent(stats_payload):
    cpu = compute_cpu_percent(stats_payload)
    assert cpu == pytest.approx(80.0, rel=1e-6)


def test_compute_memory_used_bytes_excluding_cache(stats_payload):
    used = compute_memory_used_bytes(stats_payload, exclude_cache=True)
    assert used == 400_000_000


def test_compute_memory_used_bytes_including_cache(stats_payload):
    used = compute_memory_used_bytes(stats_payload, exclude_cache=False)
    assert used == 500_000_000


def test_compute_memory_percent(stats_payload):
    used = compute_memory_used_bytes(stats_payload, exclude_cache=True)
    pct = compute_memory_percent(stats_payload, used)
    assert pct == pytest.approx(20.0, rel=1e-6)


def test_cpu_no_delta_returns_zero():
    data = {
        "cpu_stats": {"cpu_usage": {"total_usage": 10}, "system_cpu_usage": 100, "online_cpus": 2},
        "precpu_stats": {"cpu_usage": {"total_usage": 10}, "system_cpu_usage": 100},
    }
    assert compute_cpu_percent(data) == 0.0


def test_memory_percent_no_limit_returns_zero(stats_payload):
    stats_payload = dict(stats_payload)
    stats_payload["memory_stats"] = dict(stats_payload["memory_stats"], limit=0)
    used = compute_memory_used_bytes(stats_payload, exclude_cache=True)
    assert compute_memory_percent(stats_payload, used) == 0.0
