"""
Schema registry reader.

Reads schemas/registry.yaml and resolves the current version
and namespace for a given schema name.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_SCHEMAS_DIR  = Path(__file__).parent.parent.parent.parent / "ontology" / "schemas"
REGISTRY_PATH = _SCHEMAS_DIR / "registry.yaml"


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
    base = reg.get("namespace_base", "http://gep.com/ontology/")
    return f"{base}{schema_name}#"


def list_schemas() -> list[str]:
    """Return all registered schema names."""
    return [e.get("name") for e in _load().get("schemas", [])]


def load_capability_registry(schema_name: str, version: str = "") -> list[dict]:
    """
    Load `x_capability_registry` directly from the schema's root YAML.

    Read straight from the YAML file (not via Fuseki) so the diagnosis playbook
    is available even when the KG is stale, and so changing a capability needs
    no KG reload. Returns the list of capability dicts (empty list if absent).
    """
    version = version or get_current_version(schema_name)
    schema_path = _SCHEMAS_DIR / schema_name / f"v{version}" / f"{schema_name}.yaml"
    if not schema_path.exists():
        raise FileNotFoundError(
            f"Schema YAML not found for '{schema_name}' v{version}: {schema_path}"
        )
    with open(schema_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("x_capability_registry", [])
