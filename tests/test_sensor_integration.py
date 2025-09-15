from __future__ import annotations

from homeassistant.core import HomeAssistant

from ._helpers import force_refresh, get_display_name, get_unique_id, rename_in_portainer


async def test_container_sensor_unique_id_stable_and_name_updates_on_rename_integration(
    hass: HomeAssistant,
    portainer_setup,
    mock_portainer_api,
):
    await force_refresh(hass)

    sensors = [s for s in hass.states.async_all() if s.entity_id.startswith("sensor.")]
    assert sensors, "No sensors created by Portainer"
    entity_id = sensors[0].entity_id

    uid_before = get_unique_id(hass, entity_id)
    name_before = get_display_name(hass, entity_id)

    rename_in_portainer(
        module_path="custom_components.portainer.api",
        container_id="abc123",
        new_container_name="web-renamed",
        new_service_name="frontend-renamed",
    )
    await hass.config_entries.async_reload(portainer_setup.entry_id)
    await force_refresh(hass)

    uid_after = get_unique_id(hass, entity_id)
    name_after = get_display_name(hass, entity_id)

    assert uid_after == uid_before
    assert name_after != name_before
