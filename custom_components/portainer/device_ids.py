# custom_components/portainer/device_ids.py
"""Helpers to build stable DeviceInfo/identifiers for Portainer devices."""
from __future__ import annotations

from typing import Set, Tuple

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


def slug(val: str) -> str:
    """Safe slug (lowercase, spaces->_, non-alnum -> _)."""
    s = str(val).strip().lower().replace(" ", "_")
    return "".join(ch if (ch.isalnum() or ch in ("_", "-")) else "_" for ch in s)


def endpoint_identifier(endpoint_id: int | str) -> Tuple[str, str]:
    """Endpoint device identifier tuple."""
    return (DOMAIN, f"endpoint_{endpoint_id}")


def stack_identifiers(
    endpoint_id: int | str, stack_id: int | str, stack_name: str
) -> Set[Tuple[str, str]]:
    """Canonical by name + legacy by id + legacy by name."""
    sslug = slug(stack_name)
    return {
        (DOMAIN, f"stack_{endpoint_id}_{sslug}"),           # canonical (by name)
        (DOMAIN, f"stack_{endpoint_id}_{stack_id}"),        # legacy (by numeric/synth id)
        (DOMAIN, f"stack_name_{endpoint_id}_{sslug}"),      # legacy alias (old via_device)
    }


def container_identifiers(
    endpoint_id: int | str,
    container_name: str,
    compose_stack: str | None = "",
    compose_service: str | None = "",
) -> Set[Tuple[str, str]]:
    """Return multiple identifiers to avoid device splits across restarts."""
    ids: Set[Tuple[str, str]] = {
        (DOMAIN, f"container_{endpoint_id}_{slug(container_name)}")
    }
    if compose_stack and compose_service:
        ids.add(
            (DOMAIN, f"container_{endpoint_id}_{slug(compose_stack)}_{slug(compose_service)}")
        )
    return ids


def container_identifier(  # kept for backward compatibility if referenced elsewhere
    endpoint_id: int | str,
    container_name: str,
    compose_stack: str | None = "",
    compose_service: str | None = "",
) -> Tuple[str, str]:
    """Single identifier (legacy). Prefer container_identifiers() for new code."""
    if compose_stack and compose_service:
        return (
            DOMAIN,
            f"container_{endpoint_id}_{slug(compose_stack)}_{slug(compose_service)}",
        )
    return (DOMAIN, f"container_{endpoint_id}_{slug(container_name)}")


def stack_device_info(
    endpoint_id: int | str, stack_id: int | str, stack_name: str
) -> DeviceInfo:
    """DeviceInfo for a stack (child of endpoint)."""
    return DeviceInfo(
        identifiers=stack_identifiers(endpoint_id, stack_id, stack_name),
        name=f"Stack: {stack_name}",
        manufacturer="Portainer",
        via_device=endpoint_identifier(endpoint_id),
    )


def container_device_info(
    endpoint_id: int | str,
    container_name: str,
    compose_stack: str | None = "",
    compose_service: str | None = "",
) -> DeviceInfo:
    """DeviceInfo for a container (child of stack if compose, else child of endpoint)."""
    idents = container_identifiers(
        endpoint_id, container_name, compose_stack, compose_service
    )
    if compose_stack:
        parent = (DOMAIN, f"stack_{endpoint_id}_{slug(compose_stack)}")  # canonical stack id (by name)
    else:
        parent = endpoint_identifier(endpoint_id)
    return DeviceInfo(
        identifiers=idents,
        name=f"Container: {container_name}",
        manufacturer="Portainer",
        via_device=parent,
    )
