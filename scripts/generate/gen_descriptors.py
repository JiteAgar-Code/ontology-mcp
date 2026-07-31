"""
gen_descriptors.py — Generate JSON datasource descriptors from a LinkML YAML schema.

What this produces:
  A JSON file with one descriptor per class, containing:
    • datasource type (sqlserver / mongodb)
    • table or collection name
    • list of properties with their storage metadata
      (sql_column/mongo_field, sql_type, required, cross_source_check, etc.)
    • link_key: the field used to join across sources
    • login_block_conditions: properties whose values block login

  This is the file the MCP server reads to build JSON-LD responses.
  It bridges the semantic ontology (OWL/SHACL) with the physical
  storage layer (SQL column names, Mongo field names, BIT types).

Why descriptors:
  The agent needs to know not just WHAT to query, but exactly HOW:
  which table, which column name (may differ from the OWL property name),
  what SQL type to expect, and whether 0 or 1 means true.
  The OWL file has the semantics; the descriptor has the physical mapping.

Output: artifacts/{schema}/v{version}/descriptors/{schema}.descriptors.json
"""

import sys
import json
from pathlib import Path

from _yaml_loader import resolve_schema_path, artifact_dir, load_schema


def _extract_annotation(annotations: dict, key: str, default=None):
    """Safe annotation value extraction (handles missing keys)."""
    return annotations.get(key, default)


def _build_property_descriptor(slot_name: str, slot_def: dict) -> dict:
    """Build the descriptor dict for one property/slot."""
    ann = slot_def.get("annotations", {})
    prop = {
        "name":     slot_name,
        "range":    slot_def.get("range", "string"),
        "required": slot_def.get("required", False),
    }

    # Storage metadata
    sql_col  = _extract_annotation(ann, "sql_column")
    sql_type = _extract_annotation(ann, "sql_type")
    mf       = _extract_annotation(ann, "mongo_field")
    mt       = _extract_annotation(ann, "mongo_type")

    if sql_col:
        prop["sql_column"] = sql_col
    if sql_type:
        prop["sql_type"] = sql_type
        # Flag BIT columns explicitly — agent must normalize 0/1 → bool
        if sql_type == "BIT":
            prop["normalize_to_bool"] = True
    if mf:
        prop["mongo_field"] = mf
    if mt:
        prop["mongo_type"] = mt

    # Cross-source check annotation
    cs = _extract_annotation(ann, "cross_source_check")
    if cs:
        prop["cross_source_check"] = cs
        prop["normalization"] = _extract_annotation(ann, "normalization_before_compare") \
                             or _extract_annotation(ann, "normalization_note")

    # Login block conditions
    lbc = _extract_annotation(ann, "login_block_condition")
    if lbc:
        prop["login_block_condition"] = lbc

    # Co-dependency rule
    co = _extract_annotation(ann, "co_required_with")
    if co:
        prop["co_required_with"] = co

    # Derived fields
    derived = _extract_annotation(ann, "derived_from")
    if derived:
        prop["derived_from"]    = derived
        prop["derivation_rule"] = _extract_annotation(ann, "derivation_rule")

    # Enum integer mapping (for AuthenticationTypeEnum)
    if slot_def.get("range") == "AuthenticationTypeEnum":
        prop["enum_integer_map"] = {"1": "Password", "2": "SSO"}

    # OWL ObjectProperty flag
    if "OWLObjectProperties" in slot_def.get("in_subset", []):
        prop["owl_object_property"] = True
        prop["resolution_via"] = _extract_annotation(ann, "resolution_via")

    # Cross-source link
    csl = _extract_annotation(ann, "cross_source_link")
    if csl:
        prop["cross_source_link"] = csl

    return prop


def generate_descriptors(schema_name: str, version: str) -> Path:
    schema_path = resolve_schema_path(schema_name, version)
    schema_dict = load_schema(schema_name, version)
    out_dir     = artifact_dir(schema_name, version, "descriptors")
    out_file    = out_dir / f"{schema_name}.descriptors.json"

    print(f"  [gen_descriptors] reading  : {schema_path}")

    all_slots   = schema_dict.get("slots", {})
    classes     = schema_dict.get("classes", {})
    descriptors = {}

    for class_name, class_def in classes.items():
        if class_def.get("abstract"):
            continue  # skip AbstractUser — no physical table

        ann        = class_def.get("annotations", {})
        datasource = ann.get("datasource")
        if not datasource:
            continue  # skip classes without a datasource annotation

        desc = {
            "class":      class_name,
            "datasource": datasource,
            "version":    version,
        }

        # Physical location
        if datasource == "sqlserver":
            desc["table"] = ann.get("table")
        elif datasource == "mongodb":
            desc["collection"] = ann.get("collection")

        # Link key (cross-source join field)
        if ann.get("link_key"):
            desc["link_key"] = ann["link_key"]
        if ann.get("primary_key"):
            desc["primary_key"] = ann["primary_key"]
        if ann.get("foreign_key"):
            desc["foreign_key"] = ann["foreign_key"]

        # Properties
        class_slots    = class_def.get("slots", [])
        # Apply slot_usage overrides
        slot_usage_map = class_def.get("slot_usage", {})

        props = []
        for slot_name in class_slots:
            base_def = all_slots.get(slot_name, {}).copy()

            # Merge slot_usage overrides (class-level overrides top-level slot)
            if slot_name in slot_usage_map:
                override = slot_usage_map[slot_name]
                base_def.update({k: v for k, v in override.items() if k != "annotations"})
                # Merge annotations separately
                base_ann = base_def.get("annotations", {}).copy()
                base_ann.update(override.get("annotations", {}))
                base_def["annotations"] = base_ann

            if not base_def:
                continue  # slot defined on class but not in top-level slots
            props.append(_build_property_descriptor(slot_name, base_def))

        desc["properties"] = props

        # Collect login block conditions across all properties
        login_blocks = [
            {"property": p["name"], "condition": p["login_block_condition"]}
            for p in props if "login_block_condition" in p
        ]
        if login_blocks:
            desc["login_block_conditions"] = login_blocks

        descriptors[class_name] = desc

    output = {
        "schema":      schema_name,
        "version":     version,
        "namespace":   schema_dict.get("id", ""),
        "descriptors": descriptors,
    }

    out_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [gen_descriptors] written  : {out_file}")
    return out_file


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate JSON descriptors from LinkML YAML")
    parser.add_argument("--schema",  required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    generate_descriptors(args.schema, args.version)
