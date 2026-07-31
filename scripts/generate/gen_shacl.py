"""
gen_shacl.py — Generate SHACL 1.0 shapes from a LinkML YAML schema.

Two-phase approach:
  Phase 1 — LinkML auto-generation
      Uses linkml.generators.shaclgen.ShaclGenerator to produce standard
      NodeShapes for every class: required properties, range constraints,
      cardinality, pattern validation, and enum (sh:in) constraints.

  Phase 2 — Custom shape injection
      Reads the x_shacl_rules section of the YAML and appends:
        • sh:sparql constraints (PartnerMappingShape, DefaultPartnerShape)
        • custom_python shapes (MobileConsistencyShape) as rdfs:comment blocks
          — these are documentation-only in the Turtle; the Python validator
          reads the shape ID and executes the registered Python validator class.

Why SHACL:
  SHACL validates RDF graph data against declared shapes. When the MCP
  returns a JSON-LD descriptor, the agent uses pyshacl to check fetched
  data against these shapes before deciding whether to escalate to New Relic.

Output: artifacts/{schema}/v{version}/shacl/{schema}.shacl.ttl
"""

import os
import sys
import tempfile
from pathlib import Path
from textwrap import indent

import yaml

try:
    from linkml.generators.shaclgen import ShaclGenerator
except ImportError:
    sys.exit("ERROR: linkml not installed. Run: pip install linkml")

try:
    from rdflib import Graph, Namespace, URIRef, Literal, BNode
    from rdflib.namespace import RDF, RDFS, OWL, XSD, SH
except ImportError:
    sys.exit("ERROR: rdflib not installed. Run: pip install rdflib")

from _yaml_loader import resolve_schema_path, artifact_dir, load_schema

GEP = Namespace("https://gep.com/ontology/login#")


def _clean_for_linkml(schema_dict: dict) -> dict:
    """Remove x_ prefixed top-level keys — LinkML SchemaDefinition rejects them."""
    return {k: v for k, v in schema_dict.items() if not k.startswith("x_")}


def _build_sparql_shape(rule: dict, schema_prefix: str) -> str:
    """Render a SPARQL-based sh:NodeShape block as a Turtle string."""
    shape_id = rule["id"]
    target   = rule["target_class"]
    lines    = []
    for c in rule.get("constraints", []):
        if c["type"] != "sparql":
            continue
        sparql_q = c["sparql"].strip().replace("\n", "\n          ")
        msg      = c.get("message", "Constraint violation")
        lines.append(f"""
gep:{shape_id} a sh:NodeShape ;
    sh:targetClass gep:{target} ;
    sh:sparql [
        sh:message "{msg}" ;
        sh:prefixes [
            sh:declare [
                sh:prefix "gep" ;
                sh:namespace "{schema_prefix}" ;
            ]
        ] ;
        sh:select \"\"\"
          {sparql_q}
        \"\"\" ;
    ] .
""")
    return "\n".join(lines)


def _build_custom_python_shape(rule: dict) -> str:
    """
    Document a custom_python shape as a commented NodeShape.
    The Python validator reads the shape @id and dispatches to
    the registered implementation_class at runtime.
    """
    shape_id = rule["id"]
    impl     = rule.get("implementation_class", "TBD")
    msg      = rule.get("message", "")
    logic    = rule.get("logic", "").strip().replace("\n", "\n#   ")
    return f"""
# ── Custom Python Shape (not executable SHACL) ──────────────
# Shape ID   : gep:{shape_id}
# Implemented: {impl}
# Logic      :
#   {logic}
#
gep:{shape_id} a sh:NodeShape ;
    rdfs:comment "CUSTOM_PYTHON: {impl}" ;
    sh:message "{msg}" .
"""


def generate_shacl(schema_name: str, version: str) -> Path:
    schema_path = resolve_schema_path(schema_name, version)
    schema_dict = load_schema(schema_name, version)
    out_dir     = artifact_dir(schema_name, version, "shacl")
    out_file    = out_dir / f"{schema_name}.shacl.ttl"

    print(f"  [gen_shacl] reading  : {schema_path}")

    # ── Phase 1: LinkML auto-generated shapes ──────────────
    # Strip x_ keys — LinkML SchemaDefinition rejects unknown top-level fields.
    # No format= arg — LinkML 1.11 API; known formats are ['ttl'], not 'turtle'.
    clean_dict = _clean_for_linkml(schema_dict)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            yaml.dump(clean_dict, tmp, allow_unicode=True, sort_keys=False)
            tmp_path = tmp.name

        gen        = ShaclGenerator(tmp_path)
        base_shacl = gen.serialize()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # ── Phase 2: Inject custom shapes ──────────────────────
    custom_blocks = []
    ns_prefix = schema_dict.get("prefixes", {}).get("gep", "https://gep.com/ontology/login#")

    for rule in schema_dict.get("x_shacl_rules", []):
        rule_type = rule.get("type", "standard")
        if rule_type == "custom_python":
            custom_blocks.append(_build_custom_python_shape(rule))
        elif "constraints" in rule:
            for c in rule["constraints"]:
                if c.get("type") == "sparql":
                    custom_blocks.append(_build_sparql_shape(rule, ns_prefix))
                    break

    # Combine: base LinkML shapes + custom injections
    final = base_shacl
    if custom_blocks:
        final += "\n\n# ════════════════════════════════════════════════\n"
        final += "# CUSTOM SHAPES (injected by gen_shacl.py)\n"
        final += "# ════════════════════════════════════════════════\n"
        final += "\n".join(custom_blocks)

    out_file.write_text(final, encoding="utf-8")
    print(f"  [gen_shacl] written  : {out_file}")
    return out_file


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate SHACL from LinkML YAML")
    parser.add_argument("--schema",  required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    generate_shacl(args.schema, args.version)
