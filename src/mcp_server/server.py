"""
Ontology MCP Server — Knowledge Graph / Semantic Descriptor Service.

Exposes 3 KG-planning tools only. All DB/diagnostic tools are in diagnostic_server.py.
All tool descriptions are loaded from config/tool_descriptions.yaml via tool_meta.

  get_diagnosis_plan    — category → diagnosis playbook (entities, shapes, datasources)
  list_capabilities     — all supported categories (ambiguity fallback)
  get_entity_descriptor — class name → full physical column/field mapping

Intent classification is LLM-native — the agent classifies the complaint into a
category itself, then calls get_diagnosis_plan(category) once. There is no
resolve_intent tool.

Transport: stdio.
Config:    FUSEKI_URL and DEFAULT_SCHEMA from .env

Register in .vscode/mcp.json:
    "ontology-mcp": {
        "command": "python",
        "args": ["-m", "mcp_server.server"],
        "cwd": "c:\\Ontology"
    }
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from mcp.server.mcpserver import MCPServer
from mcp_server.tool_meta import get as _desc, server_description as _sdesc

FUSEKI_URL     = os.getenv("FUSEKI_URL",     "http://localhost:3030")
DEFAULT_SCHEMA = os.getenv("DEFAULT_SCHEMA", "login")

mcp = MCPServer(
    name="ontology-mcp",
    description=_sdesc("ontology_mcp"),
    version="1.0.0",
)


@mcp.tool(description=_desc("ontology_mcp", "get_diagnosis_plan"))
def get_diagnosis_plan(category: str, schema: str = DEFAULT_SCHEMA) -> str:
    """
    Args:
        category: Issue category you classified from the user's message. One of:
                  login_failure, password_reset, otp_email, sms_otp,
                  account_state, account_locked, partner_mapping, data_sync.
        schema:   Domain schema name (default: 'login').
    Returns:
        JSON playbook: capability_id, required_entities, validation_sequence,
        datasources, newrelic_tool, required_parameters.
    """
    from mcp_server.tools.get_diagnosis_plan import get_diagnosis_plan_handler
    return get_diagnosis_plan_handler(category, schema)


@mcp.tool(description=_desc("ontology_mcp", "list_capabilities"))
def list_capabilities(schema: str = DEFAULT_SCHEMA) -> str:
    """
    Args:
        schema: Domain schema name (default: 'login').
    Returns:
        JSON list of {id, category, description, covers} for every capability.
    """
    from mcp_server.tools.list_capabilities import list_capabilities_handler
    return list_capabilities_handler(schema)


@mcp.tool(description=_desc("ontology_mcp", "get_entity_descriptor"))
def get_entity_descriptor(
    class_name: str,
    schema: str = DEFAULT_SCHEMA,
    version: str = "",
) -> str:
    """
    Args:
        class_name: Short class name (e.g. 'User', 'PartnerMapping').
        schema:     Domain schema name (default: 'login').
        version:    Schema version (e.g. '1.0.0'). Empty = current.
    Returns:
        JSON entity descriptor with datasource and full property list.
    """
    from mcp_server.tools.get_descriptor import get_descriptor_handler
    return get_descriptor_handler(class_name, schema, version, FUSEKI_URL)


if __name__ == "__main__":
    mcp.run(transport="stdio")
