"""
resolve_intent tool handler.

Flow:
  1. Call SparqlClient.resolve_intent() — matches prompt → intent pattern → rows
     containing: entity IRIs, datasource/table info, rule IDs/triggers, shape IDs.
  2. For each unique entity IRI in the result, call get_entity_descriptor() to
     retrieve the full property/column mapping.
  3. Assemble everything into a JSON-LD descriptor and return as a JSON string.

The descriptor is the contract between the MCP and the agent:
  - entities     → WHERE to query (datasource + table/collection + column map)
  - validation   → WHAT to validate (SHACL shape IRIs, in order)
  - rules        → WHAT to do with the result (trigger conditions + actions)
"""

from __future__ import annotations

import json
from typing import Any


def _v(row: dict, key: str) -> str | None:
    binding = row.get(key, {})
    return binding.get("value") if isinstance(binding, dict) else None


# ── property rows → list[dict] ────────────────────────────────────────

_PROP_FIELD_MAP: dict[str, str] = {
    "sql_column":            "sqlColumn",
    "mongo_field":           "mongoField",
    "sql_type":              "sqlType",
    "required":              "required",
    "normalize_to_bool":     "normalizeToBool",
    "login_block_condition": "loginBlockCondition",
    "cross_source_link":     "crossSourceLink",
    "cross_source_check":    "crossSourceCheck",
}


def _props_from_rows(prop_rows: list[dict]) -> list[dict]:
    properties: list[dict] = []
    seen: set[str] = set()
    for row in prop_rows:
        name = _v(row, "propName") or ""
        if not name or name in seen:
            continue
        seen.add(name)
        prop: dict[str, Any] = {"name": name}
        for out_key, sparql_var in _PROP_FIELD_MAP.items():
            val = _v(row, sparql_var)
            if val:
                prop[out_key] = val
        # skip OWL Object Properties — they have no physical column or field mapping
        if not prop.get("sql_column") and not prop.get("mongo_field"):
            continue
        properties.append(prop)
    return properties


# ── descriptor assembly ───────────────────────────────────────────────

def _assemble(
    rows: list[dict],
    schema: str,
    version: str,
    entity_props: dict[str, list[dict]],
) -> dict:
    intent_name = _v(rows[0], "intentName") or "Unknown"

    # entities — deduplicated by IRI
    entities: dict[str, dict] = {}
    for row in rows:
        iri = _v(row, "entity") or ""
        if not iri or iri in entities:
            continue
        local_name = iri.split("#")[-1]
        ent: dict[str, Any] = {
            "@type":      f"gep:{local_name}",
            "class_iri":  iri,
            "datasource": _v(row, "entityDatasource") or "",
        }
        if _v(row, "entityTable"):
            ent["table"] = _v(row, "entityTable")
        if _v(row, "entityCollection"):
            ent["collection"] = _v(row, "entityCollection")
        if _v(row, "entityLinkKey"):
            ent["link_key"] = _v(row, "entityLinkKey")
        ent["properties"] = entity_props.get(iri, [])
        entities[iri] = ent

    # decision rules — deduplicated by IRI, sorted by priority
    rules: dict[str, dict] = {}
    for row in rows:
        rule_iri = _v(row, "ruleId") or ""
        if not rule_iri or rule_iri in rules:
            continue
        rule: dict[str, Any] = {
            "id":       rule_iri,
            "trigger":  _v(row, "triggerType") or "",
            "action":   _v(row, "action") or "",
            "priority": int(_v(row, "rulePriority") or 99),
        }
        if _v(row, "nrqlTemplate"):
            rule["nrql_template"] = _v(row, "nrqlTemplate")
        if _v(row, "messageTemplate"):
            rule["message_template"] = _v(row, "messageTemplate")
        rules[rule_iri] = rule

    # validation shapes — ordered as returned by SPARQL
    shapes: list[dict] = []
    seen_shapes: set[str] = set()
    for row in rows:
        sid = _v(row, "shapeId") or ""
        if sid and sid not in seen_shapes:
            seen_shapes.add(sid)
            shapes.append({"@id": sid})

    return {
        "@context":          f"artifacts/{schema}/v{version}/jsonld/{schema}.context.jsonld",
        "@type":             "gep:IntentDescriptor",
        "intent":            intent_name,
        "schema":            schema,
        "version":           version,
        "entities":          list(entities.values()),
        "validation_sequence": shapes,
        "decision_rules":    sorted(rules.values(), key=lambda r: r["priority"]),
    }


# ── public handler ────────────────────────────────────────────────────

def resolve_intent_handler(prompt: str, schema: str, fuseki_url: str) -> str:
    """
    Resolve `prompt` to a JSON-LD descriptor.
    Returns a JSON string (success or error object).
    """
    from mcp_server.kg.sparql_client import get_client
    from mcp_server.registry.schema_registry import get_current_version

    client = get_client(fuseki_url)
    try:
        version = get_current_version(schema)
    except ValueError as exc:
        return json.dumps({"error": "schema_not_found", "detail": str(exc)})

    try:
        rows = client.resolve_intent(schema, prompt)
    except Exception as exc:
        return json.dumps({"error": "sparql_failed", "detail": str(exc)})

    if not rows:
        return json.dumps({
            "error":      "no_intent_match",
            "prompt":     prompt,
            "schema":     schema,
            "suggestion": "Call list_intents to see all supported patterns.",
        })

    # Unique entity IRIs from result rows
    entity_iris = list({_v(r, "entity") or "" for r in rows} - {""})

    # Enrich each entity with its full property list (N extra SPARQL calls)
    entity_props: dict[str, list[dict]] = {}
    for iri in entity_iris:
        try:
            prop_rows = client.get_entity_descriptor(schema, iri, version)
            entity_props[iri] = _props_from_rows(prop_rows)
        except Exception:
            entity_props[iri] = []  # fail-open: entity included without properties

    descriptor = _assemble(rows, schema, version, entity_props)
    return json.dumps(descriptor, indent=2, ensure_ascii=False)
