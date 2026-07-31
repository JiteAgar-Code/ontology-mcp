"""
get_entity_descriptor tool handler.

Constructs the full entity IRI from `class_name` + namespace,
queries the descriptors graph, and returns a JSON descriptor
with datasource, table/collection, link key, and all property mappings.
"""

from __future__ import annotations

import json
from typing import Any

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

_VALID_CLASSES = ("User", "PartnerMapping", "MobileVerificationStatus", "UserDocument")


def _v(row: dict, key: str) -> str | None:
    binding = row.get(key, {})
    return binding.get("value") if isinstance(binding, dict) else None


def get_descriptor_handler(
    class_name: str, schema: str, version: str, fuseki_url: str
) -> str:
    """
    Return a JSON descriptor for one entity class.
    `class_name` is a short local name (e.g. 'User', 'PartnerMapping').
    """
    from mcp_server.kg.sparql_client import get_client
    from mcp_server.registry.schema_registry import get_current_version, get_namespace

    client = get_client(fuseki_url)
    try:
        if not version:
            version = get_current_version(schema)
        namespace = get_namespace(schema)
    except ValueError as exc:
        return json.dumps({"error": "schema_not_found", "detail": str(exc)})
    entity_iri = f"{namespace}{class_name}"

    try:
        rows = client.get_entity_descriptor(schema, entity_iri, version)
    except Exception as exc:
        return json.dumps({"error": "sparql_failed", "detail": str(exc)})

    if not rows:
        return json.dumps({
            "error":       "entity_not_found",
            "class_name":  class_name,
            "entity_iri":  entity_iri,
            "schema":      schema,
            "version":     version,
            "suggestion":  f"Valid class names: {', '.join(_VALID_CLASSES)}",
        })

    first = rows[0]
    descriptor: dict[str, Any] = {
        "@type":      f"gep:{class_name}",
        "class_iri":  entity_iri,
        "datasource": _v(first, "datasource") or "",
        "schema":     schema,
        "version":    version,
    }
    if _v(first, "tableName"):
        descriptor["table"] = _v(first, "tableName")
    if _v(first, "collectionName"):
        descriptor["collection"] = _v(first, "collectionName")
    if _v(first, "linkKey"):
        descriptor["link_key"] = _v(first, "linkKey")
    if _v(first, "primaryKey"):
        descriptor["primary_key"] = _v(first, "primaryKey")
    if _v(first, "foreignKey"):
        descriptor["foreign_key"] = _v(first, "foreignKey")

    properties: list[dict] = []
    seen: set[str] = set()
    for row in rows:
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

    descriptor["properties"] = properties
    return json.dumps(descriptor, indent=2, ensure_ascii=False)
