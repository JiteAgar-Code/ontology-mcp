"""
gen_skos.py — Generate a SKOS concept scheme from a LinkML YAML schema.

What this produces (from x_skos_scheme section):
  • skos:ConceptScheme declaration
  • skos:Concept for every class + enum in the schema
  • skos:prefLabel, skos:definition, skos:note on each concept
  • skos:inScheme linking each concept to the scheme
  • skos:topConceptOf for root concepts
  • skos:broader / skos:narrower for defined hierarchies
    (e.g. AbstractUser → User/UserDocument, BPC → partnerCode)

Why SKOS:
  SKOS provides a human-readable vocabulary layer on top of OWL.
  It enables labelling, synonyms, and concept hierarchy without
  the formal constraints of OWL class axioms. The KG stores SKOS
  triples in urn:login-kg:skos so the MCP can return human-friendly
  labels and definitions alongside machine-readable descriptors.

Output: artifacts/{schema}/v{version}/skos/{schema}.skos.ttl
"""

import sys
from pathlib import Path

try:
    from rdflib import Graph, Namespace, URIRef, Literal
    from rdflib.namespace import RDF, RDFS, SKOS, OWL, XSD
except ImportError:
    sys.exit("ERROR: rdflib not installed. Run: pip install rdflib")

from _yaml_loader import resolve_schema_path, artifact_dir, load_schema


def _ns(schema_dict: dict) -> Namespace:
    """Return the primary namespace from the schema prefixes."""
    prefix = schema_dict.get("default_prefix", "gep")
    uri    = schema_dict.get("prefixes", {}).get(prefix, "https://gep.com/ontology/login#")
    return Namespace(uri)


def _add_concept(g: Graph, gep: Namespace, concept: dict, scheme_uri: URIRef) -> None:
    """Add a single skos:Concept to the graph."""
    concept_id = concept["id"]
    uri = URIRef(concept_id.replace("gep:", str(gep)))

    g.add((uri, RDF.type, SKOS.Concept))
    g.add((uri, SKOS.inScheme, scheme_uri))

    if "prefLabel" in concept:
        g.add((uri, SKOS.prefLabel, Literal(concept["prefLabel"], lang="en")))
    if "definition" in concept:
        g.add((uri, SKOS.definition, Literal(concept["definition"], lang="en")))
    if "note" in concept:
        g.add((uri, SKOS.note, Literal(concept["note"], lang="en")))
    if concept.get("topConceptOf"):
        g.add((uri, SKOS.topConceptOf, scheme_uri))
        g.add((scheme_uri, SKOS.hasTopConcept, uri))
    if "broader" in concept:
        broader_uri = URIRef(concept["broader"].replace("gep:", str(gep)))
        g.add((uri, SKOS.broader, broader_uri))
        g.add((broader_uri, SKOS.narrower, uri))


def generate_skos(schema_name: str, version: str) -> Path:
    schema_path = resolve_schema_path(schema_name, version)
    schema_dict = load_schema(schema_name, version)
    out_dir     = artifact_dir(schema_name, version, "skos")
    out_file    = out_dir / f"{schema_name}.skos.ttl"

    print(f"  [gen_skos] reading  : {schema_path}")

    gep       = _ns(schema_dict)
    g         = Graph()
    g.bind("skos", SKOS)
    g.bind("gep",  gep)
    g.bind("owl",  OWL)

    skos_section = schema_dict.get("x_skos_scheme", {})
    if not skos_section:
        print("  [gen_skos] WARNING: no x_skos_scheme section found — writing empty file")
        out_file.write_text("", encoding="utf-8")
        return out_file

    # ── Concept Scheme ─────────────────────────────────────
    scheme_raw = skos_section["id"]
    scheme_uri = URIRef(scheme_raw.replace("gep:", str(gep)))

    g.add((scheme_uri, RDF.type, SKOS.ConceptScheme))
    g.add((scheme_uri, SKOS.prefLabel,
           Literal(skos_section.get("prefLabel", schema_name), lang="en")))
    if "description" in skos_section:
        g.add((scheme_uri, SKOS.definition,
               Literal(skos_section["description"], lang="en")))

    # ── Concepts ───────────────────────────────────────────
    for concept in skos_section.get("concepts", []):
        _add_concept(g, gep, concept, scheme_uri)

    # ── Extra hierarchies (broader/narrower between slots) ──
    for h in skos_section.get("hierarchies", []):
        broader_uri  = URIRef(h["broader"].replace("gep:", str(gep)))
        narrower_uri = URIRef(h["narrower"].replace("gep:", str(gep)))
        note         = h.get("note", "")

        # Ensure both URIs are declared as Concepts
        for uri in (broader_uri, narrower_uri):
            if (uri, RDF.type, SKOS.Concept) not in g:
                g.add((uri, RDF.type, SKOS.Concept))
                g.add((uri, SKOS.inScheme, scheme_uri))

        g.add((broader_uri,  SKOS.narrower, narrower_uri))
        g.add((narrower_uri, SKOS.broader,  broader_uri))
        if note:
            # Attach note to the narrower concept
            g.add((narrower_uri, SKOS.note, Literal(note, lang="en")))

    # ── Auto-add SKOS labels from slot/class annotations ───
    # Pull skos:prefLabel from every slot and class in the schema
    # so the KG has labels for all individual properties too.
    for slot_name, slot_def in schema_dict.get("slots", {}).items():
        annotations = slot_def.get("annotations", {})
        pref_label  = annotations.get("skos:prefLabel")
        definition  = annotations.get("skos:definition")
        note        = annotations.get("skos:note")
        if pref_label:
            slot_uri = gep[slot_name]
            if (slot_uri, RDF.type, SKOS.Concept) not in g:
                g.add((slot_uri, RDF.type, SKOS.Concept))
                g.add((slot_uri, SKOS.inScheme, scheme_uri))
            g.add((slot_uri, SKOS.prefLabel, Literal(pref_label, lang="en")))
            if definition:
                g.add((slot_uri, SKOS.definition, Literal(definition, lang="en")))
            if note:
                g.add((slot_uri, SKOS.note, Literal(str(note), lang="en")))

    ttl = g.serialize(format="turtle")
    out_file.write_text(ttl, encoding="utf-8")
    print(f"  [gen_skos] written  : {out_file}")
    return out_file


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate SKOS from LinkML YAML")
    parser.add_argument("--schema",  required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    generate_skos(args.schema, args.version)
