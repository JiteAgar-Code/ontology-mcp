"""
Shared utility: load and validate a schema YAML file.
All generator scripts import from here — single place to handle
registry resolution, path building, and x_ extension extraction.
"""

import yaml
import sys
from pathlib import Path

SCHEMAS_ROOT = Path(__file__).parent.parent.parent / "ontology" / "schemas"
ARTIFACTS_ROOT = Path(__file__).parent.parent.parent / "artifacts"


def load_registry() -> dict:
    registry_path = SCHEMAS_ROOT / "registry.yaml"
    if not registry_path.exists():
        sys.exit(f"ERROR: registry.yaml not found at {registry_path}")
    with open(registry_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_schema_path(schema_name: str, version: str) -> Path:
    """Return the Path to a versioned schema YAML, or exit with a clear error."""
    registry = load_registry()
    for entry in registry.get("schemas", []):
        if entry["name"] == schema_name:
            versioned = SCHEMAS_ROOT / schema_name / f"v{version}" / f"{schema_name}.yaml"
            if not versioned.exists():
                sys.exit(
                    f"ERROR: schema '{schema_name}' version '{version}' not found at {versioned}"
                )
            return versioned
    sys.exit(f"ERROR: schema '{schema_name}' not registered in registry.yaml")


def load_schema(schema_name: str, version: str) -> dict:
    """Load and return the full schema dict (including x_ extensions)."""
    path = resolve_schema_path(schema_name, version)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def artifact_dir(schema_name: str, version: str, artifact_type: str) -> Path:
    """Return (and ensure exists) the output directory for a given artifact type."""
    d = ARTIFACTS_ROOT / schema_name / f"v{version}" / artifact_type
    d.mkdir(parents=True, exist_ok=True)
    return d
