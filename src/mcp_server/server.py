"""
MCP Ontology Server — Semantic Descriptor Service.

Exposes 3 tools to Claude Code via stdio transport:

  resolve_intent        — natural-language prompt → JSON-LD descriptor
                          (entities + datasource mappings + SHACL shapes + rules)
  get_entity_descriptor — class name → full physical column/field mapping
  list_intents          — list all intent patterns the KG can resolve

Transport: stdio. Claude Code spawns this as a child process.
Config:    FUSEKI_URL and DEFAULT_SCHEMA read from .env (or environment).

Start directly for testing:
    python -m mcp_server.server

Register with Claude Code in .claude/settings.json:
    "mcpServers": {
        "ontology-mcp": {
            "command": "python",
            "args": ["-m", "mcp_server.server"],
            "cwd": "c:\\\\Ontology"
        }
    }
"""

import os
import sys
from pathlib import Path

# Allow `python -m mcp_server.server` from any directory
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

from mcp.server.mcpserver import MCPServer

FUSEKI_URL     = os.getenv("FUSEKI_URL",     "http://localhost:3030")
DEFAULT_SCHEMA = os.getenv("DEFAULT_SCHEMA", "login")

mcp = MCPServer(
    name="ontology-mcp",
    description=(
        "Semantic Descriptor Service for the Login Query Agent. "
        "Queries the OWL/SHACL/SKOS Knowledge Graph in Apache Jena Fuseki "
        "and returns JSON-LD descriptors that tell the agent WHERE to query "
        "(datasource + table/column mappings), WHAT to validate (SHACL shapes), "
        "and HOW to route results (decision rules)."
    ),
    version="1.0.0",
)


# ─────────────────────────── tools ────────────────────────────────────

@mcp.tool(
    description=(
        "Resolve a natural-language prompt to a JSON-LD descriptor. "
        "Returns: (1) every entity the agent must query with its datasource, "
        "table/collection, and full column mapping; (2) SHACL shape IRIs to "
        "validate the results; (3) decision rules specifying what to do based "
        "on validation outcome (e.g. query New Relic if all shapes pass, "
        "report block reason if LoginBlockShape fails). "
        "Example prompts: 'user cannot login', 'why is login failing', "
        "'check partner mapping for user'."
    )
)
def resolve_intent(
    prompt: str,
    schema: str = DEFAULT_SCHEMA,
) -> str:
    """
    Args:
        prompt: The user's question or symptom description (free text).
        schema: Domain schema name (default: 'login').
    Returns:
        JSON string — gep:IntentDescriptor with entities, validation_sequence,
        and decision_rules. Returns an error object if no pattern matches.
    """
    from mcp_server.tools.resolve_intent import resolve_intent_handler
    return resolve_intent_handler(prompt, schema, FUSEKI_URL)


@mcp.tool(
    description=(
        "Get the full physical descriptor for a specific entity class. "
        "Returns datasource, table or collection name, link key, primary key, "
        "and all property mappings (SQL column, MongoDB field, type, "
        "normalization flags, login-block conditions, cross-source links). "
        "Valid class names for the 'login' schema: "
        "User, PartnerMapping, MobileVerificationStatus, UserDocument."
    )
)
def get_entity_descriptor(
    class_name: str,
    schema:  str = DEFAULT_SCHEMA,
    version: str = "",
) -> str:
    """
    Args:
        class_name: Short local class name (e.g. 'User', 'PartnerMapping').
        schema:     Domain schema name (default: 'login').
        version:    Specific version string (e.g. '1.0.0'). Empty = use current.
    Returns:
        JSON string — entity descriptor with datasource and properties list.
    """
    from mcp_server.tools.get_descriptor import get_descriptor_handler
    return get_descriptor_handler(class_name, schema, version, FUSEKI_URL)


@mcp.tool(
    description=(
        "List all intent patterns the KG can resolve for a given schema. "
        "Use this to discover what kinds of prompts are supported before "
        "calling resolve_intent. Returns intent names and their text patterns."
    )
)
def list_intents(schema: str = DEFAULT_SCHEMA) -> str:
    """
    Args:
        schema: Domain schema name (default: 'login').
    Returns:
        JSON string — list of {intent, patterns[]} objects plus usage hint.
    """
    from mcp_server.tools.list_intents import list_intents_handler
    return list_intents_handler(schema, FUSEKI_URL)


# ─────────────────────────── entry point ──────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
