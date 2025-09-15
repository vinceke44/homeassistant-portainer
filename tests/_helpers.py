from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


async def force_refresh(hass: HomeAssistant) -> None:
    await hass.async_block_till_done()
    await hass.async_block_till_done()


def get_display_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    if state is None:
        raise AssertionError(f"Missing state: {entity_id}")
    if state.name:
        return state.name
    friendly = state.attributes.get("friendly_name")
    if friendly:
        return str(friendly)
    ent = er.async_get(hass).async_get(entity_id)
    if ent and ent.name:
        return str(ent.name)
    return entity_id


def get_unique_id(hass: HomeAssistant, entity_id: str) -> str:
    ent = er.async_get(hass).async_get(entity_id)
    if not ent or not ent.unique_id:
        raise AssertionError(f"Missing unique_id: {entity_id}")
    return ent.unique_id


def rename_in_portainer(
    *,
    module_path: str,
    container_id: str,
    new_container_name: str | None = None,
    new_service_name: str | None = None,
) -> None:
    mod = __import__(module_path, fromlist=["*"])
    api = getattr(mod, "_TEST_API_STORE", None)
    if api is None:
        raise RuntimeError("Test API store not found (mock_portainer_api not initialized).")
    if new_container_name:
        cont = api["containers"].get(container_id)
        if cont:
            cont["Name"] = new_container_name
            cont["Names"] = [f"/{new_container_name}"]
    if new_service_name:
        svc = api["services_by_container"].get(container_id)
        if svc:
            svc["Spec"]["Name"] = new_service_name
