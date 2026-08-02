"""
gen_owl.py — Generate OWL 2 DL Turtle from a LinkML YAML schema.

What this produces:
  • owl:Class for every class (with rdfs:subClassOf for is_a)
  • owl:DatatypeProperty for every slot with a primitive range (string, integer, boolean)
  • owl:ObjectProperty for every slot with a class range (hasUser, hasMobileVerificationStatus)
  • owl:AnnotationProperty for skos:prefLabel, skos:definition, skos:note
  • rdfs:domain / rdfs:range on all properties
  • owl:equivalentClass with owl:intersectionOf for required slot enforcement
  • Enum classes as owl:Class with owl:oneOf individuals

Why OWL:
  OWL gives the KG formal semantics. An OWL reasoner can infer that
  a User with hasUser pointing to a PartnerMapping is related, or detect
  inconsistencies (e.g. an islocked value outside {0,1}).

Output: artifacts/{schema}/v{version}/owl/{schema}.owl.ttl
"""

import os
import sys
import tempfile
from pathlib import Path

import yaml

try:
    from linkml.generators.owlgen import OwlSchemaGenerator
except ImportError:
    sys.exit("ERROR: linkml not installed. Run: pip install linkml")

from _yaml_loader import resolve_schema_path, artifact_dir, load_schema


def _clean_for_linkml(schema_dict: dict) -> dict:
    """
    Remove x_ keys and local imports before passing to LinkML generators.
    Local imports are already merged by _load_and_merge(); keeping them in
    the temp file would cause OwlSchemaGenerator (via SchemaView) to chase
    paths that don't exist next to the temp file and fail.
    Only linkml: imports remain — generators resolve these internally.
    """
    cleaned = {k: v for k, v in schema_dict.items() if not k.startswith("x_")}
    cleaned["imports"] = [i for i in cleaned.get("imports", []) if i.startswith("linkml:")]
    return cleaned


def generate_owl(schema_name: str, version: str) -> Path:
    schema_path = resolve_schema_path(schema_name, version)
    schema_dict = load_schema(schema_name, version)
    out_dir     = artifact_dir(schema_name, version, "owl")
    out_file    = out_dir / f"{schema_name}.owl.ttl"

    print(f"  [gen_owl] reading  : {schema_path}")

    # Strip x_ custom keys — LinkML generators reject unknown top-level fields
    clean_dict = _clean_for_linkml(schema_dict)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            yaml.dump(clean_dict, tmp, allow_unicode=True, sort_keys=False)
            tmp_path = tmp.name

        # OwlSchemaGenerator with metaclasses=False keeps output clean.
        # type_objects=False emits primitive ranges as xsd: datatypes.
        # No format= arg — LinkML 1.11 resolves format via serialize().
        gen      = OwlSchemaGenerator(
            tmp_path,
            metaclasses=False,
            type_objects=False,
            skip_vacuous_min_zero_cardinality_axioms=True,
            skip_vacuous_local_range_axioms=True,
            consolidate_cardinality_axioms=True,
        )
        owl_text = gen.serialize()

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    out_file.write_text(owl_text, encoding="utf-8")
    print(f"  [gen_owl] written  : {out_file}")
    return out_file


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate OWL from LinkML YAML")
    parser.add_argument("--schema",  required=True, help="Schema name (e.g. login)")
    parser.add_argument("--version", required=True, help="Schema version (e.g. 1.0.0)")
    args = parser.parse_args()
    generate_owl(args.schema, args.version)
