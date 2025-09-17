"""Diagnostics support for Portainer."""
from __future__ import annotations

from typing import Any, Dict

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, TO_REDACT


def _stats_snapshot(coord: Any) -> Dict[str, Any]:
    """Compact snapshot of one stats coordinator (CPU/Mem + trimmed raw)."""
    data = getattr(coord, "data", None)
    if not data:
        return {
            "last_update_success": getattr(coord, "last_update_success", None),
            "cpu_percent": None,
            "mem_used_mib": None,
            "mem_percent": None,
            "raw_sample": None,
        }

    raw = getattr(data, "raw", {}) or {}
    # Keep only relevant sections for CPU/memory computations
    raw_sample = {
        "cpu_stats": raw.get("cpu_stats", {}),
        "precpu_stats": raw.get("precpu_stats", {}),
        "memory_stats": raw.get("memory_stats", {}),
    }
    try:
        cpu = float(getattr(data, "cpu_percent", 0.0))
    except Exception:
        cpu = 0.0
    try:
        mem_mib = float(getattr(data, "mem_used_mib", 0.0))
    except Exception:
        mem_mib = 0.0
    try:
        mem_pct = float(getattr(data, "mem_percent", 0.0))
    except Exception:
        mem_pct = 0.0

    return {
        "last_update_success": getattr(coord, "last_update_success", None),
        "cpu_percent": round(cpu, 3),
        "mem_used_mib": round(mem_mib, 2),
        "mem_percent": round(mem_pct, 3),
        "raw_sample": raw_sample,
    }


def _get_main_data_block(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return the main data block while handling both dict/obj namespaces."""
    ns = (hass.data.get(DOMAIN, {}) or {}).get(entry.entry_id)
    if ns is None:
        return {}
    # Historical variant: ns was a coordinator object with `.data`
    if hasattr(ns, "data"):
        return getattr(ns, "data") or {}
    # Current variant: dict namespace with 'coordinator'
    if isinstance(ns, dict):
        coord = ns.get("coordinator")
        if coord is None:
            return {}
        # Prefer raw_data (rich), fallback to data if present
        return getattr(coord, "raw_data", None) or getattr(coord, "data", {}) or {}
    return {}


def _collect_stats_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    """Build a small stats section from cached per-container stats coordinators."""
    ns = (hass.data.get(DOMAIN, {}) or {}).get(entry.entry_id, {})
    stats_ns: Dict[str, Any] = {}
    if isinstance(ns, dict):
        stats_ns = ns.get("stats_coordinators", {}) or {}

    out: Dict[str, Any] = {
        "endpoints_loaded": [],
        "containers_indexed": [],
        "stats": {},
    }

    # Try to include a bit of context from the main coordinator if available
    coord = ns.get("coordinator") if isinstance(ns, dict) else None
    if coord and getattr(coord, "raw_data", None):
        endpoints = list((coord.raw_data.get("endpoints") or {}).keys())
        by_name = coord.raw_data.get("containers_by_name") or {}
        out["endpoints_loaded"] = endpoints
        out["containers_indexed"] = sorted(list(by_name.keys()))

    # One compact block per container_key (endpoint:name)
    for container_key, c in stats_ns.items():
        out["stats"][container_key] = _stats_snapshot(c)

    return out


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    entry_block = {
        "data": async_redact_data(config_entry.data, TO_REDACT),
        "options": async_redact_data(config_entry.options, TO_REDACT),
    }

    data_block = async_redact_data(
        _get_main_data_block(hass, config_entry), TO_REDACT
    )

    stats_block = _collect_stats_diagnostics(hass, config_entry)

    return {
        "entry": entry_block,
        "data": data_block,
        "stats": stats_block,
    }
