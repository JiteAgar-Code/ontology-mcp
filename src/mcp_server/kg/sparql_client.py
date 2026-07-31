"""
SPARQL client for the MCP Ontology Server.

Queries Apache Jena Fuseki via HTTP (application/sparql-results+json).
Reads the meta graph to discover active version's named graph URIs,
then substitutes them into SPARQL template files in sparql/.

The meta graph holds a single subject <urn:kg:{schema}:> with predicates:
  urn:kg:currentVersion, urn:kg:activeOntologyGraph,
  urn:kg:activeShaclGraph, urn:kg:activeSkosGraph,
  urn:kg:activeDescriptorsGraph, urn:kg:activeRulesGraph,
  urn:kg:activeIntentsGraph
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests

SPARQL_DIR = Path(__file__).parent.parent.parent.parent / "ontology" / "sparql"

# Characters that could enable SPARQL injection if embedded in a FILTER literal.
_INJECT_RE = re.compile(r'["\'\\\x00-\x1f]')


class SparqlClient:
    def __init__(self, fuseki_base: str = "http://localhost:3030") -> None:
        self.fuseki_base = fuseki_base.rstrip("/")
        # Cache: schema → {varName → graphIRI, ...}  (version pointer included)
        self._graphs_cache: dict[str, dict[str, str]] = {}

    # ── low-level ─────────────────────────────────────────────────────

    def _dataset_url(self, schema: str) -> str:
        return f"{self.fuseki_base}/{schema}-kg"

    def _query(self, schema: str, sparql: str) -> list[dict[str, Any]]:
        r = requests.post(
            f"{self._dataset_url(schema)}/sparql",
            data={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
            timeout=15,
        )
        try:
            r.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Fuseki query failed (HTTP {r.status_code}): {r.text[:300]}"
            ) from exc
        return r.json()["results"]["bindings"]

    def _load_template(self, filename: str) -> str:
        path = SPARQL_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"SPARQL template not found: {path}")
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _sanitise(text: str) -> str:
        """Strip SPARQL-injection characters; truncate to 200 chars."""
        return _INJECT_RE.sub("", text)[:200]

    # ── meta graph: active version resolution ─────────────────────────

    def get_active_graphs(self, schema: str) -> dict[str, str]:
        """
        Return the active version's named graph URIs for `schema`.
        Keys: version, ontologyGraph, shaclGraph, skosGraph,
              descriptorsGraph, rulesGraph, intentsGraph.
        Result is cached for the lifetime of this client instance.
        """
        if schema in self._graphs_cache:
            return self._graphs_cache[schema]

        meta_iri = f"urn:kg:{schema}:meta"
        root_iri = f"urn:kg:{schema}:"
        q = f"""
SELECT ?version ?ontologyGraph ?shaclGraph ?skosGraph
       ?descriptorsGraph ?rulesGraph ?intentsGraph
WHERE {{
    GRAPH <{meta_iri}> {{
        <{root_iri}> <urn:kg:currentVersion>        ?version ;
                     <urn:kg:activeOntologyGraph>    ?ontologyGraph ;
                     <urn:kg:activeShaclGraph>        ?shaclGraph ;
                     <urn:kg:activeSkosGraph>         ?skosGraph ;
                     <urn:kg:activeDescriptorsGraph>  ?descriptorsGraph ;
                     <urn:kg:activeRulesGraph>        ?rulesGraph ;
                     <urn:kg:activeIntentsGraph>      ?intentsGraph .
    }}
}}
"""
        rows = self._query(schema, q)
        if not rows:
            raise RuntimeError(
                f"No active version pointer for schema '{schema}'. "
                f"Run: python scripts/load_kg.py --schema {schema} --version 1.0.0 "
                f"&& python scripts/promote.py --schema {schema} --version 1.0.0"
            )
        graphs = {k: rows[0][k]["value"] for k in rows[0]}
        self._graphs_cache[schema] = graphs
        return graphs

    # ── tool-facing queries ───────────────────────────────────────────

    def resolve_intent(self, schema: str, prompt: str) -> list[dict]:
        """
        Match `prompt` against intent text patterns in the KG.
        Returns SPARQL bindings with entity, datasource, rule, and shape data.
        """
        graphs   = self.get_active_graphs(schema)
        template = self._load_template("resolve_intent.sparql")
        query = (
            template
            .replace("__INTENTS_GRAPH__",     graphs["intentsGraph"])
            .replace("__DESCRIPTORS_GRAPH__", graphs["descriptorsGraph"])
            .replace("__RULES_GRAPH__",       graphs["rulesGraph"])
            .replace("__INTENT_TEXT__",       self._sanitise(prompt.lower()))
        )
        return self._query(schema, query)

    def get_entity_descriptor(
        self, schema: str, entity_iri: str, version: str = ""
    ) -> list[dict]:
        """
        Return all rows for one entity's physical descriptor (columns, types, flags).
        """
        graphs     = self.get_active_graphs(schema)
        desc_graph = graphs.get("descriptorsGraph",
                                f"urn:kg:{schema}:v{version or '1.0.0'}:descriptors")
        template   = self._load_template("get_entity_descriptor.sparql")
        query = (
            template
            .replace("__DESCRIPTORS_GRAPH__", desc_graph)
            .replace("__ENTITY_IRI__",         entity_iri)
        )
        return self._query(schema, query)

    def list_intents(self, schema: str) -> list[dict]:
        """Return all intent names + text patterns for `schema`."""
        graphs   = self.get_active_graphs(schema)
        template = self._load_template("list_intents.sparql")
        return self._query(
            schema,
            template.replace("__INTENTS_GRAPH__", graphs["intentsGraph"])
        )

    def get_decision_rules(self, schema: str) -> list[dict]:
        """Return all decision rules ordered by priority."""
        graphs   = self.get_active_graphs(schema)
        template = self._load_template("get_decision_rules.sparql")
        return self._query(
            schema,
            template.replace("__RULES_GRAPH__", graphs["rulesGraph"])
        )


# ── module-level singleton ────────────────────────────────────────────

_client: SparqlClient | None = None


def get_client(fuseki_url: str = "http://localhost:3030") -> SparqlClient:
    """Return (or create) the shared SparqlClient for this process."""
    global _client
    if _client is None:
        _client = SparqlClient(fuseki_url)
    return _client
