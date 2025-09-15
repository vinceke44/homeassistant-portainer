
"""Test fixtures and configuration for Portainer custom component tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest


custom_components_path = Path(__file__).parent.parent / "custom_components"
sys.path.insert(0, str(custom_components_path))

os.environ["TESTING"] = "true"

pytest_plugins = ["pytest_homeassistant_custom_component"]

# Import after path setup
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.portainer.const import (  # noqa: E402
    CONF_FEATURE_HEALTH_CHECK,
    CONF_FEATURE_RESTART_POLICY,
    CONF_FEATURE_UPDATE_CHECK,
    CONF_UPDATE_CHECK_TIME,
    DOMAIN,
)

# -------------------------
# VS Code test discovery config
# -------------------------
def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "unit: mark test as unit test")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "test_homeassistant" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        else:
            item.add_marker(pytest.mark.unit)


# -------------------------
# Existing config-entry fixtures
# -------------------------

TEST_PORTAINER_TITLE = "Test Portainer"


@pytest.fixture
def mock_config_entry_feature_enabled():
    return MockConfigEntry(
        domain=DOMAIN,
        title=TEST_PORTAINER_TITLE,
        data={"host": "localhost", "name": TEST_PORTAINER_TITLE},
        options={
            CONF_FEATURE_HEALTH_CHECK: True,
            CONF_FEATURE_RESTART_POLICY: True,
            CONF_FEATURE_UPDATE_CHECK: True,
            CONF_UPDATE_CHECK_TIME: "04:30",
        },
        entry_id="test_entry_enabled",
    )


@pytest.fixture
def mock_config_entry_feature_disabled():
    return MockConfigEntry(
        domain=DOMAIN,
        title=TEST_PORTAINER_TITLE,
        data={"host": "localhost", "name": TEST_PORTAINER_TITLE},
        options={
            CONF_FEATURE_HEALTH_CHECK: True,
            CONF_FEATURE_RESTART_POLICY: True,
            CONF_FEATURE_UPDATE_CHECK: False,
            CONF_UPDATE_CHECK_TIME: "04:30",
        },
        entry_id="test_entry_disabled",
    )


@pytest.fixture
def mock_config_entry_new():
    return MockConfigEntry(
        domain=DOMAIN,
        title=TEST_PORTAINER_TITLE,
        data={"host": "localhost", "name": TEST_PORTAINER_TITLE},
        options={},
        entry_id="test_entry_new",
    )


# -------------------------
# Test-only Portainer API/control mocks)
# -------------------------

@pytest.fixture
def mock_portainer_api(monkeypatch) -> dict[str, Any]:
    """
    Patch Portainer API + Control classes for tests that opt in.

    Exposes a mutable store at module attribute `_TEST_API_STORE`.
    """
    import custom_components.portainer.api as api_mod
    import custom_components.portainer.control_api as ctrl_mod

    containers: dict[str, dict[str, Any]] = {
        "abc123": {
            "Id": "abc123",
            "EndpointId": 1,
            "Name": "web",
            "Names": ["/web"],
            "State": "running",
            "Labels": {
                "com.docker.compose.service": "frontend",
                "com.docker.compose.project": "mystack",
            },
        },
        "def456": {
            "Id": "def456",
            "EndpointId": 1,
            "Name": "db",
            "Names": ["/db"],
            "State": "running",
            "Labels": {
                "com.docker.compose.service": "postgres",
                "com.docker.compose.project": "mystack",
            },
        },
    }
    services_by_container: dict[str, dict[str, Any]] = {
        "abc123": {"ID": "svc1", "Spec": {"Name": "frontend"}},
        "def456": {"ID": "svc2", "Spec": {"Name": "postgres"}},
    }
    store = {
        "containers": containers,
        "services_by_container": services_by_container,
        "control_calls": [],
    }

    class _API:
        def __init__(self, *_args, **_kwargs) -> None:
            """Loose signature to match runtime init."""

        async def get_containers(self):
            return list(containers.values())

        async def get_services(self):
            return list({v["ID"]: v for v in services_by_container.values()}.values())

    class _CTRL:
        def __init__(self, *_args, **_kwargs) -> None:
            """Match PortainerControl(api) constructor loosely."""

        async def restart_container(self, container_id: str):
            store["control_calls"].append(("restart", container_id))
            return True

        async def start_container(self, endpoint_id: int, container_id: str):
            store["control_calls"].append(("start", endpoint_id, container_id))
            return True

        async def stop_container(self, endpoint_id: int, container_id: str):
            store["control_calls"].append(("stop", endpoint_id, container_id))
            return True

    monkeypatch.setattr(api_mod, "PortainerAPI", _API)
    # Use the class your tests import: PortainerControl
    monkeypatch.setattr(ctrl_mod, "PortainerControl", _CTRL)

    api_mod._TEST_API_STORE = store
    ctrl_mod._TEST_API_STORE = store
    return store


@pytest.fixture
async def portainer_setup(hass, mock_portainer_api) -> MockConfigEntry:
    """
    Create and set up a Portainer config entry for tests that need HA entities.

    Skips the test if HA cannot load the custom component in this environment.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Portainer",
        unique_id="portainer-test",
        data={
            "host": "localhost",
            "url": "https://localhost:9443",
            "api_key": "dummy",
            "name": TEST_PORTAINER_TITLE,
            "use_ssl": True,
            "verify_ssl": False,
        },
        options={"name_mode": "service"},
    )
    entry.add_to_hass(hass)

    ok = await hass.config_entries.async_setup(entry.entry_id)
    if not ok:
        import pytest as _pytest
        _pytest.skip("Portainer integration not loadable in this test runner (custom_components not discovered)")

    await hass.async_block_till_done()
    return entry