"""
promote.py — Promote a schema version to 'current' in the Knowledge Graph.

Usage:
    python scripts/promote.py --schema login --version 1.0.0
    python scripts/promote.py --schema login --version 1.1.0  # after loading v1.1.0
    python scripts/promote.py --schema login --version 1.0.0  # rollback to v1.0.0

What it does:
    1. Verifies that the target version's graphs exist and are non-empty in Fuseki.
    2. Atomically updates urn:kg:{schema}:meta so currentVersion → target version.

The old version's graphs are NEVER deleted — rollback is always possible.

Prerequisites: Fuseki must be running with the schema loaded (load_kg.py run first).
"""

import sys
import argparse
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("ERROR: requests not installed. Run: pip install requests")

sys.path.insert(0, str(Path(__file__).parent))


# ── KG IRI helpers ────────────────────────────────────────────────────

def _graph_iri(schema: str, version: str, graph_type: str) -> str:
    return f"urn:kg:{schema}:v{version}:{graph_type}"

def _meta_iri(schema: str) -> str:
    return f"urn:kg:{schema}:meta"

def _schema_iri(schema: str) -> str:
    return f"urn:kg:{schema}:"

GRAPH_TYPES = ["ontology", "shacl", "skos", "descriptors", "rules"]


# ── SPARQL helpers ────────────────────────────────────────────────────

def _sparql_ask(fuseki_base: str, graph_uri: str) -> bool:
    """Return True if the named graph exists and contains at least one triple."""
    query = f"ASK {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
    r = requests.post(
        f"{fuseki_base}/sparql",
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("boolean", False)


def _sparql_select_meta(fuseki_base: str, schema: str) -> dict | None:
    """
    Return the current meta graph contents as a dict, or None if not set.
    """
    meta = _meta_iri(schema)
    root = _schema_iri(schema)
    query = f"""
SELECT ?version ?ontologyGraph ?shaclGraph ?skosGraph ?descriptorsGraph ?rulesGraph
WHERE {{
    GRAPH <{meta}> {{
        <{root}> <urn:kg:currentVersion>        ?version ;
                 <urn:kg:activeOntologyGraph>    ?ontologyGraph ;
                 <urn:kg:activeShaclGraph>        ?shaclGraph ;
                 <urn:kg:activeSkosGraph>         ?skosGraph ;
                 <urn:kg:activeDescriptorsGraph>  ?descriptorsGraph ;
                 <urn:kg:activeRulesGraph>        ?rulesGraph .
    }}
}}
"""
    r = requests.post(
        f"{fuseki_base}/sparql",
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=10,
    )
    r.raise_for_status()
    bindings = r.json().get("results", {}).get("bindings", [])
    if not bindings:
        return None
    row = bindings[0]
    return {k: row[k]["value"] for k in row}


def _sparql_update(fuseki_base: str, update_str: str) -> None:
    r = requests.post(
        f"{fuseki_base}/update",
        data={"update": update_str},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if r.status_code not in (200, 204):
        raise RuntimeError(f"SPARQL UPDATE failed: HTTP {r.status_code} — {r.text[:200]}")


def _build_meta_update(schema: str, version: str) -> str:
    meta   = _meta_iri(schema)
    root   = _schema_iri(schema)
    lines  = "\n".join(
        f'                 <urn:kg:active{t.capitalize()}Graph> <{_graph_iri(schema, version, t)}> ;'
        for t in GRAPH_TYPES
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
{lines}
                 .
    }}
}}
""".strip()


# ── Main promote logic ────────────────────────────────────────────────

def promote(schema: str, version: str, fuseki_url: str) -> bool:
    dataset     = f"{schema}-kg"
    fuseki_base = f"{fuseki_url.rstrip('/')}/{dataset}"

    print(f"\n{'═'*60}")
    print(f"  promote.py  →  {schema}  v{version}")
    print(f"  Fuseki: {fuseki_base}")
    print(f"{'═'*60}")

    # ── Check current version ─────────────────────────────────────
    print("\n  Current meta graph state:")
    try:
        current = _sparql_select_meta(fuseki_base, schema)
    except Exception as exc:
        sys.exit(f"\nERROR: Could not query Fuseki: {exc}\n"
                 "  → Is Fuseki running? java -jar infra/fuseki/fuseki-server.jar --config infra/fuseki/config/login-kg.ttl")

    if current:
        print(f"    currentVersion = {current.get('version', '?')}")
    else:
        print("    (no meta entry yet — first promotion)")

    # ── Verify target version graphs exist ────────────────────────
    print(f"\n  Verifying graphs for v{version}:")
    missing = []
    for graph_type in GRAPH_TYPES:
        uri   = _graph_iri(schema, version, graph_type)
        found = _sparql_ask(fuseki_base, uri)
        status = "✅" if found else "❌ MISSING"
        print(f"    {graph_type:<14} {status}  <{uri}>")
        if not found:
            missing.append(graph_type)

    if missing:
        print(f"\nERROR: {len(missing)} graph(s) not loaded for v{version}: {missing}")
        print(f"  → Run first: python scripts/load_kg.py --schema {schema} --version {version}")
        return False

    # ── Update meta graph ─────────────────────────────────────────
    print(f"\n  Updating meta graph → currentVersion = {version}")
    update = _build_meta_update(schema, version)
    _sparql_update(fuseki_base, update)

    # ── Verify ───────────────────────────────────────────────────
    after = _sparql_select_meta(fuseki_base, schema)
    promoted_version = after.get("version", "?") if after else "?"

    if promoted_version == version:
        print(f"\n  ✅ Promoted successfully. {schema} current = v{version}")
        if current and current.get("version") != version:
            old = current["version"]
            print(f"\n  Old version v{old} graphs remain — to roll back:")
            print(f"    python scripts/promote.py --schema {schema} --version {old}")
    else:
        print(f"\n  ❌ Promotion verification failed — meta shows version: {promoted_version}")
        return False

    return True


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Promote a schema version to current in the KG"
    )
    parser.add_argument("--schema",  required=True, help="Schema name (e.g. login)")
    parser.add_argument("--version", required=True, help="Version to promote (e.g. 1.0.0)")
    parser.add_argument(
        "--fuseki", default="http://localhost:3030",
        help="Fuseki base URL (default: http://localhost:3030)"
    )
    args = parser.parse_args()
    success = promote(args.schema, args.version, args.fuseki)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
