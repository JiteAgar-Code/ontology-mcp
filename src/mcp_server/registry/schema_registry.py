"""
Schema registry reader.

Reads schemas/registry.yaml and resolves the current version
and namespace for a given schema name.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).parent.parent.parent.parent / "ontology" / "schemas" / "registry.yaml"


def _load() -> dict:
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_current_version(schema_name: str) -> str:
    """Return the current_version string for `schema_name` from registry.yaml."""
    reg = _load()
    for entry in reg.get("schemas", []):
        if entry.get("name") == schema_name:
            return entry["current_version"]
    available = [e.get("name") for e in reg.get("schemas", [])]
    raise ValueError(
        f"Schema '{schema_name}' not in registry. Available: {available}"
    )


def get_namespace(schema_name: str) -> str:
    """Return the OWL namespace IRI for `schema_name` (ends with '#')."""
    reg  = _load()
    base = reg.get("namespace_base", "https://gep.com/ontology/")
    return f"{base}{schema_name}#"


def list_schemas() -> list[str]:
    """Return all registered schema names."""
    return [e.get("name") for e in _load().get("schemas", [])]
