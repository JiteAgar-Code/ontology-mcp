"""
gen_rules.py — Generate KG decision-rule triples from a LinkML YAML schema.

What this produces:
  RDF/Turtle triples representing the x_decision_rules section.
  Each rule becomes a named individual of type gep:DecisionRule with:
    • gep:rulePriority     — integer, evaluated in order
    • gep:triggerType      — ALL_SHAPES_PASS | SHAPE_VIOLATION | CROSS_SOURCE_MISMATCH
    • gep:targetShape      — IRI of the SHACL shape (for SHAPE_VIOLATION rules)
    • gep:action           — query_newrelic | report_mismatch | report_block_reason
    • gep:messageTemplate  — Literal string with {placeholders}
    • gep:nrqlTemplate     — Literal string (for query_newrelic rules)
    • gep:involvedField    — (for CROSS_SOURCE_MISMATCH) each field IRI

  These triples are loaded into urn:login-kg:rules in Fuseki.
  The MCP server queries this graph to decide which action to take
  after the agent has run SHACL validation on fetched data.

Why rules as triples:
  Storing rules in the KG (not hard-coded in Python) makes them
  versionable, inspectable via SPARQL, and updatable without a code
  deploy. Adding a new rule = update the YAML, regenerate, reload KG.

Output: artifacts/{schema}/v{version}/rules/{schema}.rules.ttl
"""

import sys
from pathlib import Path

try:
    from rdflib import Graph, Namespace, URIRef, Literal
    from rdflib.namespace import RDF, RDFS, XSD
except ImportError:
    sys.exit("ERROR: rdflib not installed. Run: pip install rdflib")

from _yaml_loader import resolve_schema_path, artifact_dir, load_schema


def generate_rules(schema_name: str, version: str) -> Path:
    schema_path = resolve_schema_path(schema_name, version)
    schema_dict = load_schema(schema_name, version)
    out_dir     = artifact_dir(schema_name, version, "rules")
    out_file    = out_dir / f"{schema_name}.rules.ttl"

    print(f"  [gen_rules] reading  : {schema_path}")

    ns_uri = schema_dict.get("prefixes", {}).get(
        schema_dict.get("default_prefix", "gep"),
        "http://gep.com/ontology/login#"
    )
    GEP = Namespace(ns_uri)

    g = Graph()
    g.bind("gep",  GEP)
    g.bind("xsd",  XSD)
    g.bind("rdfs", RDFS)

    # ── Declare gep:DecisionRule class ────────────────────
    DR = GEP.DecisionRule
    g.add((DR, RDF.type,        URIRef("http://www.w3.org/2002/07/owl#Class")))
    g.add((DR, RDFS.label,      Literal("Decision Rule", lang="en")))
    g.add((DR, RDFS.comment,    Literal(
        "A rule that determines what action to take based on SHACL validation results.", lang="en"
    )))

    # ── Properties (declared once) ────────────────────────
    _declare_prop(g, GEP, "rulePriority",    "Rule Priority",    XSD.integer)
    _declare_prop(g, GEP, "triggerType",     "Trigger Type",     XSD.string)
    _declare_prop(g, GEP, "action",          "Action",           XSD.string)
    _declare_prop(g, GEP, "messageTemplate", "Message Template", XSD.string)
    _declare_prop(g, GEP, "nrqlTemplate",    "NRQL Template",    XSD.string)
    _declare_prop(g, GEP, "targetShape",     "Target Shape",     None)   # ObjectProperty
    _declare_prop(g, GEP, "involvedField",   "Involved Field",   None)   # ObjectProperty

    # ── Rule individuals ──────────────────────────────────
    for rule in schema_dict.get("x_decision_rules", []):
        rule_uri = GEP[rule["id"]]

        g.add((rule_uri, RDF.type,       DR))
        g.add((rule_uri, RDF.type,       URIRef("http://www.w3.org/2002/07/owl#NamedIndividual")))
        g.add((rule_uri, RDFS.label,     Literal(rule.get("name", rule["id"]), lang="en")))
        g.add((rule_uri, RDFS.comment,   Literal(rule.get("description", ""), lang="en")))
        g.add((rule_uri, GEP.rulePriority,
               Literal(rule.get("priority", 99), datatype=XSD.integer)))
        g.add((rule_uri, GEP.triggerType,
               Literal(rule.get("trigger", ""), datatype=XSD.string)))
        g.add((rule_uri, GEP.action,
               Literal(rule.get("action", ""), datatype=XSD.string)))

        if "message_template" in rule:
            g.add((rule_uri, GEP.messageTemplate,
                   Literal(rule["message_template"].strip(), datatype=XSD.string)))

        if "nrql_template" in rule:
            g.add((rule_uri, GEP.nrqlTemplate,
                   Literal(rule["nrql_template"].strip(), datatype=XSD.string)))

        if "shape" in rule:
            g.add((rule_uri, GEP.targetShape, GEP[rule["shape"]]))

        for field in rule.get("fields", []):
            # field like "MobileVerificationStatus.isMobileNumberVerifiedSQL"
            cls, prop = field.split(".") if "." in field else (field, field)
            g.add((rule_uri, GEP.involvedField, GEP[prop]))

    ttl = g.serialize(format="turtle")
    out_file.write_text(ttl, encoding="utf-8")
    print(f"  [gen_rules] written  : {out_file}")
    return out_file


def _declare_prop(g: Graph, ns: Namespace, local: str, label: str, datatype) -> None:
    """Declare a GEP property (datatype or object) once in the graph."""
    uri = ns[local]
    OWL_NS = URIRef("http://www.w3.org/2002/07/owl#")
    prop_type = URIRef(str(OWL_NS) + ("DatatypeProperty" if datatype else "ObjectProperty"))
    g.add((uri, RDF.type,   prop_type))
    g.add((uri, RDFS.label, Literal(label, lang="en")))
    if datatype:
        g.add((uri, URIRef("http://www.w3.org/2000/01/rdf-schema#range"), datatype))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate decision-rule triples from LinkML YAML")
    parser.add_argument("--schema",  required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    generate_rules(args.schema, args.version)
