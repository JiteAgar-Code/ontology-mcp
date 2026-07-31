"""
list_intents tool handler.

Returns all intent names and their text patterns for a schema,
grouped by intent name, as a JSON object.
"""

from __future__ import annotations

import json


def _v(row: dict, key: str) -> str | None:
    binding = row.get(key, {})
    return binding.get("value") if isinstance(binding, dict) else None


def list_intents_handler(schema: str, fuseki_url: str) -> str:
    """
    Return all known intent patterns for `schema` as a JSON string.
    """
    from mcp_server.kg.sparql_client import get_client
    from mcp_server.registry.schema_registry import get_current_version

    client = get_client(fuseki_url)
    try:
        version = get_current_version(schema)
    except ValueError as exc:
        return json.dumps({"error": "schema_not_found", "detail": str(exc)})

    try:
        rows = client.list_intents(schema)
    except Exception as exc:
        return json.dumps({"error": "sparql_failed", "detail": str(exc)})

    # Group patterns under intent name (SPARQL may return one row per pattern)
    intents: dict[str, dict] = {}
    for row in rows:
        name    = _v(row, "intentName") or "Unknown"
        pattern = _v(row, "textPattern") or ""
        if name not in intents:
            intents[name] = {"intent": name, "patterns": []}
        if pattern and pattern not in intents[name]["patterns"]:
            intents[name]["patterns"].append(pattern)

    return json.dumps(
        {
            "schema":  schema,
            "version": version,
            "count":   len(intents),
            "intents": list(intents.values()),
            "usage": (
                "Pass any text containing one of these patterns to resolve_intent. "
                "Matching is case-insensitive substring search."
            ),
        },
        indent=2,
        ensure_ascii=False,
    )
