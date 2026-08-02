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
    """Load the full schema dict, recursively merging all imported sub-files."""
    path = resolve_schema_path(schema_name, version)
    return _load_and_merge(path)


def _load_and_merge(path: Path) -> dict:
    """
    Load a LinkML YAML and recursively merge classes/slots/types/enums/subsets
    from every local import. Skips linkml: and URL imports (framework-handled).
    New sub-files added to shared/ or entities/ are picked up automatically
    as long as they are listed in the root schema's imports section.
    """
    with open(path, encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    for import_ref in schema.get("imports", []):
        if import_ref.startswith("linkml:") or "://" in import_ref:
            continue
        import_path = path.parent / f"{import_ref}.yaml"
        if not import_path.exists():
            sys.exit(f"ERROR: import '{import_ref}' not found at {import_path}")
        imported = _load_and_merge(import_path)
        for key in ("classes", "slots", "types", "enums", "subsets"):
            if key in imported:
                schema.setdefault(key, {})
                schema[key].update(imported[key])

    return schema


def artifact_dir(schema_name: str, version: str, artifact_type: str) -> Path:
    """Return (and ensure exists) the output directory for a given artifact type."""
    d = ARTIFACTS_ROOT / schema_name / f"v{version}" / artifact_type
    d.mkdir(parents=True, exist_ok=True)
    return d
