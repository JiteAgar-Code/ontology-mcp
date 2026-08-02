"""
load_kg.py — Load ontology artifacts into Apache Jena / Fuseki Knowledge Graph.

Usage:
    python scripts/load_kg.py --schema login --version 1.0.0
    python scripts/load_kg.py --schema login --version 1.0.0 --fuseki http://localhost:3030
    python scripts/load_kg.py --schema login --version 1.0.0 --dry-run

What it loads (5 named graphs):
    urn:kg:{schema}:v{version}:ontology     ← login.owl.ttl
    urn:kg:{schema}:v{version}:shacl        ← login.shacl.ttl
    urn:kg:{schema}:v{version}:skos         ← login.skos.ttl
    urn:kg:{schema}:v{version}:rules        ← login.rules.ttl
    urn:kg:{schema}:v{version}:descriptors  ← login.descriptors.json (converted to RDF)

Diagnosis playbooks (x_capability_registry) are read directly from the schema
YAML at query time — they are NOT loaded into the KG.

Then updates:
    urn:kg:{schema}:meta                    ← version pointer (currentVersion → this version)

Prerequisites:
    1. Java 11+  — https://adoptium.net  (Eclipse Temurin 17 or 21 LTS recommended)
    2. Fuseki JAR — https://jena.apache.org/download/
                    Download: apache-jena-fuseki-X.Y.Z.zip → extract fuseki-server.jar
                    Place at: infra/fuseki/fuseki-server.jar
    3. Start Fuseki (from project root):
         java -jar infra/fuseki/fuseki-server.jar --config infra/fuseki/config/login-kg.ttl
    4. Fuseki UI: http://localhost:3030/  (verify login-kg dataset is listed)
"""

import sys
import json
import argparse
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("ERROR: requests not installed. Run: pip install requests")

try:
    import yaml
except ImportError:
    sys.exit("ERROR: pyyaml not installed. Run: pip install pyyaml")

try:
    from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS
    from rdflib.namespace import XSD
except ImportError:
    sys.exit("ERROR: rdflib not installed. Run: pip install rdflib")

sys.path.insert(0, str(Path(__file__).parent.parent / "generate"))
from _yaml_loader import load_schema, ARTIFACTS_ROOT

# ── KG vocabulary ─────────────────────────────────────────────────────
# Used in the descriptors graph.
# These terms are specific to our KG loading process, not LinkML-generated.
_EntityDescriptor   = "EntityDescriptor"
_PropertyDescriptor = "PropertyDescriptor"


# ── Named graph IRI helpers ───────────────────────────────────────────

def _graph_iri(schema: str, version: str, graph_type: str) -> str:
    return f"urn:kg:{schema}:v{version}:{graph_type}"

def _meta_iri(schema: str) -> str:
    return f"urn:kg:{schema}:meta"

def _schema_iri(schema: str) -> str:
    return f"urn:kg:{schema}:"


# ── Fuseki HTTP helpers ───────────────────────────────────────────────

def _health_check(fuseki_base: str) -> None:
    """Verify Fuseki is running and the dataset exists."""
    try:
        r = requests.get(f"{fuseki_base}/sparql", params={"query": "ASK {}"}, timeout=5)
        r.raise_for_status()
    except requests.exceptions.ConnectionError:
        sys.exit(
            f"\nERROR: Cannot connect to Fuseki at {fuseki_base}\n"
            "  → Start Fuseki: java -jar infra/fuseki/fuseki-server.jar --config infra/fuseki/config/login-kg.ttl\n"
            "  → Verify Java 11+ is installed: java -version\n"
        )
    except requests.exceptions.HTTPError as e:
        sys.exit(f"\nERROR: Fuseki health check failed: {e}\n")


def _put_graph(fuseki_base: str, graph_uri: str, ttl_content: str, dry_run: bool) -> None:
    """
    Load a Turtle string into a named graph via Graph Store Protocol HTTP PUT.
    PUT replaces the entire named graph — idempotent, safe to re-run.
    """
    if dry_run:
        g_tmp = Graph()
        g_tmp.parse(data=ttl_content, format="turtle")
        print(f"    [DRY-RUN] would PUT {len(g_tmp)} triples → <{graph_uri}>")
        return

    r = requests.put(
        f"{fuseki_base}/data",
        params={"graph": graph_uri},
        data=ttl_content.encode("utf-8"),
        headers={"Content-Type": "text/turtle; charset=utf-8"},
        timeout=30,
    )
    if r.status_code not in (200, 201, 204):
        raise RuntimeError(f"GSP PUT failed: HTTP {r.status_code} — {r.text[:200]}")


def _sparql_update(fuseki_base: str, update_str: str, dry_run: bool) -> None:
    """Execute a SPARQL 1.1 Update against the Fuseki update endpoint."""
    if dry_run:
        print(f"    [DRY-RUN] would SPARQL UPDATE ({len(update_str)} chars)")
        return

    r = requests.post(
        f"{fuseki_base}/update",
        data={"update": update_str},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if r.status_code not in (200, 204):
        raise RuntimeError(f"SPARQL UPDATE failed: HTTP {r.status_code} — {r.text[:200]}")


# ── Descriptors JSON → RDF ────────────────────────────────────────────

def _descriptors_to_rdf(desc_json: dict) -> str:
    """
    Convert login.descriptors.json to Turtle RDF.

    JSON → RDF vocabulary:
      gep:EntityDescriptor   — one per entity class
      gep:PropertyDescriptor — one per (entity, property) pair, named gep:{Class}__{prop}
      gep:datasource         — "sqlserver" or "mongodb"
      gep:tableName          — SQL table name
      gep:collectionName     — MongoDB collection name
      gep:hasProperty        — links EntityDescriptor → PropertyDescriptor
      gep:sqlColumn          — SQL column name
      gep:mongoField         — MongoDB field name
      gep:normalizeToBool    — true if BIT 0/1 must be normalized
      gep:loginBlockCondition — condition string that blocks login
    """
    namespace = desc_json.get("namespace", "http://gep.com/ontology/login#")
    if not namespace.endswith("#"):
        namespace += "#"

    GEP = Namespace(namespace)
    g   = Graph()
    g.bind("gep",  GEP)
    g.bind("rdfs", RDFS)
    g.bind("xsd",  XSD)

    EntityDescriptor   = GEP[_EntityDescriptor]
    PropertyDescriptor = GEP[_PropertyDescriptor]

    for class_name, desc in desc_json.get("descriptors", {}).items():
        entity_uri = GEP[class_name]
        g.add((entity_uri, RDF.type, EntityDescriptor))

        if desc.get("datasource"):
            g.add((entity_uri, GEP.datasource, Literal(desc["datasource"])))
        if desc.get("table"):
            g.add((entity_uri, GEP.tableName, Literal(desc["table"])))
        if desc.get("collection"):
            g.add((entity_uri, GEP.collectionName, Literal(desc["collection"])))
        if desc.get("link_key"):
            g.add((entity_uri, GEP.linkKey, Literal(desc["link_key"])))
        if desc.get("primary_key"):
            g.add((entity_uri, GEP.primaryKey, Literal(desc["primary_key"])))
        if desc.get("foreign_key"):
            g.add((entity_uri, GEP.foreignKey, Literal(desc["foreign_key"])))

        for prop in desc.get("properties", []):
            prop_name = prop.get("name", "")
            if not prop_name:
                continue
            prop_uri = GEP[f"{class_name}__{prop_name}"]
            g.add((prop_uri, RDF.type, PropertyDescriptor))
            g.add((prop_uri, GEP.ofEntity,      entity_uri))
            g.add((prop_uri, GEP.propertyName,  Literal(prop_name)))
            g.add((entity_uri, GEP.hasProperty, prop_uri))

            for key, pred in [
                ("sql_column",            GEP.sqlColumn),
                ("mongo_field",           GEP.mongoField),
                ("sql_type",              GEP.sqlType),
                ("login_block_condition", GEP.loginBlockCondition),
                ("cross_source_link",     GEP.crossSourceLink),
                ("cross_source_check",    GEP.crossSourceCheck),
                ("derived_from",          GEP.derivedFrom),
            ]:
                if prop.get(key):
                    g.add((prop_uri, pred, Literal(str(prop[key]))))

            if prop.get("required") is not None:
                g.add((prop_uri, GEP.required, Literal(bool(prop["required"]))))
            if prop.get("normalize_to_bool"):
                g.add((prop_uri, GEP.normalizeToBool, Literal(True)))
            if prop.get("owl_object_property"):
                g.add((prop_uri, GEP.isObjectProperty, Literal(True)))

    return g.serialize(format="turtle")


# ── Meta graph update ─────────────────────────────────────────────────

def _build_meta_update(schema: str, version: str) -> str:
    """
    SPARQL UPDATE that atomically replaces the meta graph contents.
    DELETE WHERE removes all existing triples; INSERT DATA writes fresh ones.
    Note: active_triples are predicate-object pairs only (subject already open via ;).
    """
    meta  = _meta_iri(schema)
    root  = _schema_iri(schema)
    types = ["ontology", "shacl", "skos", "descriptors", "rules"]
    # Predicate-object pairs only — subject (<root>) is already open from the ; chain above
    active_triples = "\n".join(
        f'                 <urn:kg:active{t.capitalize()}Graph> <{_graph_iri(schema, version, t)}> ;'
        for t in types
    )
    return f"""
DELETE WHERE {{
    GRAPH <{meta}> {{ ?s ?p ?o }}
}} ;
INSERT DATA {{
    GRAPH <{meta}> {{
        <{root}> a                       <urn:kg:SchemaRegistry> ;
                 <urn:kg:schema>          "{schema}" ;
                 <urn:kg:currentVersion>  "{version}" ;
{active_triples}
                 .
    }}
}}
""".strip()


# ── Main load orchestration ───────────────────────────────────────────

def load_kg(schema: str, version: str, fuseki_url: str, dry_run: bool) -> bool:
    dataset   = f"{schema}-kg"
    fuseki_base = f"{fuseki_url.rstrip('/')}/{dataset}"
    arts_base   = ARTIFACTS_ROOT / schema / f"v{version}"

    print(f"\n{'═'*60}")
    print(f"  KG Load Pipeline")
    print(f"  Schema  : {schema}  v{version}")
    print(f"  Fuseki  : {fuseki_base}")
    print(f"  Dry run : {dry_run}")
    print(f"{'═'*60}")

    if not dry_run:
        print("\n  Checking Fuseki connectivity...")
        _health_check(fuseki_base)
        print("  Fuseki OK")

    schema_dict    = load_schema(schema, version)
    namespace      = schema_dict.get("id", f"http://gep.com/ontology/{schema}#")

    # ── Artifact file paths ───────────────────────────────────────
    ttl_graphs = [
        ("ontology",    arts_base / "owl"   / f"{schema}.owl.ttl"),
        ("shacl",       arts_base / "shacl" / f"{schema}.shacl.ttl"),
        ("skos",        arts_base / "skos"  / f"{schema}.skos.ttl"),
        ("rules",       arts_base / "rules" / f"{schema}.rules.ttl"),
    ]
    desc_path     = arts_base / "descriptors" / f"{schema}.descriptors.json"
    template_path = arts_base / "jsonld"       / f"{schema}.agent_template.json"

    # ── Verify all artifacts exist ────────────────────────────────
    missing = []
    for _, p in ttl_graphs:
        if not p.exists():
            missing.append(str(p))
    for p in (desc_path, template_path):
        if not p.exists():
            missing.append(str(p))
    if missing:
        print("\nERROR: Missing artifacts — run generate.py first:")
        for m in missing:
            print(f"  missing: {m}")
        return False

    results = {}
    overall_start = time.time()

    # ── Stage 1: Load 4 TTL files directly ───────────────────────
    for graph_type, path in ttl_graphs:
        print(f"\n▶ [{graph_type.upper()}]")
        t = time.time()
        try:
            ttl = path.read_text(encoding="utf-8")
            g_uri = _graph_iri(schema, version, graph_type)
            _put_graph(fuseki_base, g_uri, ttl, dry_run)
            results[graph_type] = ("✅ OK", time.time() - t)
            print(f"  → <{g_uri}>")
            print(f"  └─ done in {time.time() - t:.2f}s")
        except Exception as exc:
            results[graph_type] = (f"❌ FAILED: {exc}", time.time() - t)
            print(f"  └─ FAILED: {exc}")

    # ── Stage 2: Descriptors JSON → RDF ──────────────────────────
    print("\n▶ [DESCRIPTORS]")
    t = time.time()
    try:
        desc_json = json.loads(desc_path.read_text(encoding="utf-8"))
        desc_ttl  = _descriptors_to_rdf(desc_json)
        g_uri     = _graph_iri(schema, version, "descriptors")
        _put_graph(fuseki_base, g_uri, desc_ttl, dry_run)
        results["descriptors"] = ("✅ OK", time.time() - t)
        print(f"  → <{g_uri}>")
        print(f"  └─ done in {time.time() - t:.2f}s")
    except Exception as exc:
        results["descriptors"] = (f"❌ FAILED: {exc}", time.time() - t)
        print(f"  └─ FAILED: {exc}")

    # ── Stage 3: Update meta graph ────────────────────────────────
    print("\n▶ [META]")
    t = time.time()
    try:
        update = _build_meta_update(schema, version)
        _sparql_update(fuseki_base, update, dry_run)
        results["meta"] = ("✅ OK", time.time() - t)
        print(f"  → <{_meta_iri(schema)}>  currentVersion = {version}")
        print(f"  └─ done in {time.time() - t:.2f}s")
    except Exception as exc:
        results["meta"] = (f"❌ FAILED: {exc}", time.time() - t)
        print(f"  └─ FAILED: {exc}")

    # ── Summary ───────────────────────────────────────────────────
    total   = time.time() - overall_start
    all_ok  = all(s.startswith("✅") for s, _ in results.values())
    print(f"\n{'─'*60}")
    print(f"  Load Summary  ({total:.2f}s total)")
    print(f"{'─'*60}")
    for stage, (status, elapsed) in results.items():
        print(f"  {stage:<14} {status}  ({elapsed:.2f}s)")
    print(f"{'─'*60}")
    if all_ok and not dry_run:
        print(f"\n  KG loaded. Now promote this version as current:")
        print(f"  python scripts/promote.py --schema {schema} --version {version}\n")
    return all_ok


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Load ontology artifacts into Apache Jena/Fuseki KG"
    )
    parser.add_argument("--schema",  required=True, help="Schema name (e.g. login)")
    parser.add_argument("--version", required=True, help="Schema version (e.g. 1.0.0)")
    parser.add_argument(
        "--fuseki", default="http://localhost:3030",
        help="Fuseki base URL (default: http://localhost:3030)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be loaded without hitting Fuseki"
    )
    args = parser.parse_args()
    success = load_kg(args.schema, args.version, args.fuseki, args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
