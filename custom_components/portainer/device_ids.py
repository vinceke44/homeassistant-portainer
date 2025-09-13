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
    """Primary ID by numeric stack id + secondary alias by stack name."""
    return {
        (DOMAIN, f"stack_{endpoint_id}_{stack_id}"),
        (DOMAIN, f"stack_name_{endpoint_id}_{slug(stack_name)}"),
    }


def container_identifier(
    endpoint_id: int | str,
    container_name: str,
    compose_stack: str | None = "",
    compose_service: str | None = "",
) -> Tuple[str, str]:
    """Stable container device id; prefer stack+service when available."""
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
    ident = {
        container_identifier(
            endpoint_id, container_name, compose_stack, compose_service
        )
    }
    if compose_stack and compose_service:
        parent = (DOMAIN, f"stack_name_{endpoint_id}_{slug(compose_stack)}")
    else:
        parent = endpoint_identifier(endpoint_id)
    return DeviceInfo(
        identifiers=ident,
        name=f"Container: {container_name}",
        manufacturer="Portainer",
        via_device=parent,
    )

