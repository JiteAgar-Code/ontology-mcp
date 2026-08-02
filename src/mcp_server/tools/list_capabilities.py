"""
list_capabilities tool handler.

Returns all supported diagnosis categories with their descriptions and `covers`
metadata. The agent calls this ONLY when it genuinely cannot classify the user's
complaint into a category — not on every query.
"""

from __future__ import annotations

import json


def list_capabilities_handler(schema: str) -> str:
    """Return all capabilities (id, category, description, covers) as JSON."""
    from mcp_server.registry.schema_registry import (
        load_capability_registry,
        get_current_version,
    )

    try:
        version = get_current_version(schema)
    except ValueError as exc:
        return json.dumps({"error": "schema_not_found", "detail": str(exc)})

    try:
        registry = load_capability_registry(schema, version)
    except Exception as exc:
        return json.dumps({"error": "registry_load_failed", "detail": str(exc)})

    capabilities = [
        {
            "id":          cap.get("id"),
            "category":    cap.get("category"),
            "description": cap.get("description", ""),
            "covers":      cap.get("covers", []),
        }
        for cap in registry
    ]

    return json.dumps({
        "schema":       schema,
        "version":      version,
        "count":        len(capabilities),
        "capabilities": capabilities,
        "usage": (
            "`covers` is descriptive only — do NOT string-match against it. "
            "Reason about which category best fits, then call "
            "get_diagnosis_plan(category) once."
        ),
    }, indent=2, ensure_ascii=False)
