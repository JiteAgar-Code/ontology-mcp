"""
get_diagnosis_plan tool handler.

Called ONCE by the agent AFTER it classifies the user's complaint into a
category (LLM-native — no tool call for classification). Returns the structured
diagnosis playbook for that category from x_capability_registry.

The returned `capability_id` is the token every data-mcp tool requires — it is
the enforcement handshake that guarantees the agent came through the ontology
layer before touching live data.
"""

from __future__ import annotations

import json


def get_diagnosis_plan_handler(category: str, schema: str) -> str:
    """
    Return the diagnosis playbook for `category` as a JSON string.

    On an exact category match: capability_id, required_entities,
    validation_sequence, datasources, newrelic_tool, required_parameters,
    additional_checks, matched=true.

    On no match: matched=false plus the list of available categories so the
    agent can pick the right one (or fall back to list_capabilities).
    """
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

    wanted = (category or "").strip().lower()

    for cap in registry:
        if cap.get("category", "").lower() == wanted:
            return json.dumps({
                "matched":             True,
                "capability_id":       cap.get("id"),
                "category":            cap.get("category"),
                "description":         cap.get("description", ""),
                "required_parameters": cap.get("required_parameters", []),
                "required_entities":   cap.get("required_entities", []),
                "validation_sequence": cap.get("validation_sequence", []),
                "datasources":         cap.get("datasources", {}),
                "newrelic_tool":       cap.get("newrelic_tool"),
                "additional_checks":   cap.get("additional_checks", []),
                "schema":              schema,
                "version":             version,
                "next_step": (
                    "Pass capability_id to every data-mcp tool. Fetch the "
                    "required_entities, then call validate_login_shapes with the "
                    "validation_sequence. Escalate to newrelic_tool only if "
                    "all_shapes_pass=true and newrelic_tool is not null."
                ),
            }, indent=2, ensure_ascii=False)

    # No exact match — return the menu so the agent can re-pick.
    available = [
        {"category": c.get("category"), "description": c.get("description", "")}
        for c in registry
    ]
    return json.dumps({
        "matched":            False,
        "category":           category,
        "detail":             f"No capability with category '{category}'.",
        "available_categories": available,
        "suggestion": (
            "Pick the closest category from available_categories and call "
            "get_diagnosis_plan again, or call list_capabilities for full detail."
        ),
    }, indent=2, ensure_ascii=False)
