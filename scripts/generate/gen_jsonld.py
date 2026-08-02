"""
gen_jsonld.py — Generate a JSON-LD context + agent descriptor template.

Two outputs:

  1. {schema}.context.jsonld
     A standard JSON-LD @context mapping property shortnames to full URIs.
     Used by the agent to interpret any JSON-LD response from the MCP.
     Example:
       "username" → "http://gep.com/ontology/login#username"
       "isLocked" → "http://gep.com/ontology/login#isLocked"

  2. {schema}.agent_template.json
     A JSON template showing the exact structure the MCP will return
     for each intent. The agent uses this as the contract for what
     fields to expect in a resolve_intent() response.
     Includes: entities, datasource, properties, shapes, decision rules.

Why JSON-LD:
  JSON-LD adds a semantic layer to plain JSON. Each field name in the
  MCP response maps to a globally unique OWL property URI. This means
  the agent's responses are interoperable, self-describing, and can be
  loaded into the KG as instance data.

Output: artifacts/{schema}/v{version}/jsonld/{schema}.context.jsonld
        artifacts/{schema}/v{version}/jsonld/{schema}.agent_template.json
"""

import sys
import json
from pathlib import Path

from _yaml_loader import resolve_schema_path, artifact_dir, load_schema

# XSD type map from LinkML range names to JSON-LD @type values
XSD_TYPE_MAP = {
    "string":  "xsd:string",
    "integer": "xsd:integer",
    "boolean": "xsd:boolean",
    "float":   "xsd:float",
    "double":  "xsd:double",
    "date":    "xsd:date",
    "datetime":"xsd:dateTime",
    "uri":     "@id",
    "SqlBit":  "xsd:integer",
}


def _slot_jsonld_entry(slot_name: str, slot_def: dict, ns_uri: str) -> dict:
    """Build the JSON-LD @context entry for one slot."""
    range_val = slot_def.get("range", "string")
    entry = {"@id": f"{ns_uri}{slot_name}"}

    xsd_type = XSD_TYPE_MAP.get(range_val)
    if xsd_type == "@id":
        entry["@type"] = "@id"
    elif xsd_type:
        entry["@type"] = xsd_type

    if slot_def.get("multivalued"):
        entry["@container"] = "@set"

    return entry


def generate_jsonld(schema_name: str, version: str) -> tuple[Path, Path]:
    schema_path = resolve_schema_path(schema_name, version)
    schema_dict = load_schema(schema_name, version)
    out_dir     = artifact_dir(schema_name, version, "jsonld")

    ns_uri      = schema_dict.get("prefixes", {}).get(
        schema_dict.get("default_prefix", "gep"),
        "http://gep.com/ontology/login#"
    )

    print(f"  [gen_jsonld] reading  : {schema_path}")

    # ── 1. JSON-LD @context ───────────────────────────────
    context = {
        "@version": 1.1,
        "gep":   ns_uri,
        "xsd":   "http://www.w3.org/2001/XMLSchema#",
        "skos":  "http://www.w3.org/2004/02/skos/core#",
        "owl":   "http://www.w3.org/2002/07/owl#",
        "rdfs":  "http://www.w3.org/2000/01/rdf-schema#",
    }

    # Map every class to its URI
    for class_name in schema_dict.get("classes", {}):
        context[class_name] = {"@id": f"{ns_uri}{class_name}", "@type": "@id"}

    # Map every slot to its URI + type
    for slot_name, slot_def in schema_dict.get("slots", {}).items():
        context[slot_name] = _slot_jsonld_entry(slot_name, slot_def, ns_uri)

    # Map enum values
    for enum_name, enum_def in schema_dict.get("enums", {}).items():
        context[enum_name] = {"@id": f"{ns_uri}{enum_name}", "@type": "@id"}
        for val_name in enum_def.get("permissible_values", {}):
            context[val_name] = {"@id": f"{ns_uri}{val_name}"}

    context_doc = {"@context": context}
    ctx_file = out_dir / f"{schema_name}.context.jsonld"
    ctx_file.write_text(json.dumps(context_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [gen_jsonld] written  : {ctx_file}")

    # ── 2. Agent response template ────────────────────────
    # One entry per intent — shows the agent exactly what fields to expect.
    templates = []
    for intent in schema_dict.get("x_intents", []):
        entity_descriptors = []
        for entity_name in intent.get("entities", []):
            class_def = schema_dict.get("classes", {}).get(entity_name, {})
            ann       = class_def.get("annotations", {})
            slots     = class_def.get("slots", [])
            all_slots = schema_dict.get("slots", {})

            props = []
            for s in slots:
                sd = all_slots.get(s, {})
                entry = {
                    "name":     s,
                    "required": sd.get("required", False),
                    "range":    sd.get("range", "string"),
                }
                sa = sd.get("annotations", {})
                if sa.get("sql_column"):
                    entry["sql_column"] = sa["sql_column"]
                if sa.get("mongo_field"):
                    entry["mongo_field"] = sa["mongo_field"]
                if sa.get("sql_type") == "BIT":
                    entry["normalize_to_bool"] = True
                if sa.get("login_block_condition"):
                    entry["login_block_condition"] = sa["login_block_condition"]
                props.append(entry)

            entity_descriptors.append({
                "@type":      f"gep:{entity_name}",
                "datasource": ann.get("datasource"),
                "table":      ann.get("table"),
                "collection": ann.get("collection"),
                "link_key":   ann.get("link_key") or ann.get("primary_key"),
                "properties": props,
            })

        templates.append({
            "@context":    f"./{{schema}}.context.jsonld",
            "@type":       "gep:IntentDescriptor",
            "intent_id":   intent["id"],
            "intent_name": intent["name"],
            "entities":    entity_descriptors,
            "validation_sequence": [
                {"@id": f"gep:{s}"} for s in intent.get("validation_sequence", [])
            ],
            "decision_rules": [
                {"@id": f"gep:{r}"}
                for r in [
                    dr["id"]
                    for dr in schema_dict.get("x_decision_rules", [])
                ]
            ],
        })

    template_doc = {
        "@context": context_doc["@context"],
        "schema":   schema_name,
        "version":  version,
        "intents":  templates,
    }
    tmpl_file = out_dir / f"{schema_name}.agent_template.json"
    tmpl_file.write_text(json.dumps(template_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [gen_jsonld] written  : {tmpl_file}")

    return ctx_file, tmpl_file


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate JSON-LD context from LinkML YAML")
    parser.add_argument("--schema",  required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    generate_jsonld(args.schema, args.version)
