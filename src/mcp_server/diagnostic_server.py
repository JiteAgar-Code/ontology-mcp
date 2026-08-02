"""
Data MCP Server — Live DB queries + shape validation + New Relic.

Exposes 7 tools for executing the diagnosis plan returned by ontology-mcp/get_diagnosis_plan.
All tools require capability_id from get_diagnosis_plan — calling without it returns a
structured error directing the agent back to ontology-mcp.

All tool descriptions are loaded from config/tool_descriptions.yaml via tool_meta.

Call order after get_diagnosis_plan:
  Step 1a  query_sql_user               — UM_Users
  Step 1b  query_sql_mobile_verification — UM_UserMobileNumberVerified
  Step 1c  query_sql_partner_mappings   — UM_UserPartnermapping
  Step 1d  query_mongo_user             — MongoDB users collection
  Step 2   validate_login_shapes        — SHACL shape evaluation
  Step 3a  query_newrelic_login_mfa     — dr_010 (login / MFA / OTP)
  Step 3b  query_newrelic_reset_password — dr_011 (reset password)

Transport: stdio.
Config:    SQL/Mongo/NR credentials from .env

Register in .vscode/mcp.json:
    "data-mcp": {
        "command": "python",
        "args": ["-m", "mcp_server.diagnostic_server"],
        "cwd": "c:\\Ontology"
    }
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from mcp.server.mcpserver import MCPServer
from mcp_server.tool_meta import get as _desc, server_description as _sdesc

mcp = MCPServer(
    name="data-mcp",
    description=_sdesc("data_mcp"),
    version="1.0.0",
)


# ── capability_id gate ────────────────────────────────────────────────────────

def _check_capability_id(capability_id: str) -> str | None:
    """
    Returns a JSON error string if capability_id is absent, else None.
    Enforces that ontology-mcp/get_diagnosis_plan is always called first.
    """
    if not capability_id or not capability_id.strip():
        return json.dumps({
            "error":     "capability_id_required",
            "detail":    (
                "All data-mcp tools require a capability_id obtained from "
                "ontology-mcp/get_diagnosis_plan. You have not retrieved a "
                "diagnosis plan yet."
            ),
            "next_step": (
                "Classify the user's complaint into a category yourself, then call "
                "ontology-mcp → get_diagnosis_plan(category). Use the returned "
                "capability_id in every subsequent data-mcp tool call."
            ),
        }, indent=2)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1  —  SQL Server queries (one tool per table)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool(description=_desc("data_mcp", "query_sql_user"))
def query_sql_user(username: str, capability_id: str = "") -> str:
    """
    Args:
        username:  Username or email address to look up.
        capability_id: Returned by ontology-mcp/get_diagnosis_plan. Required.
    Returns:
        JSON with UM_Users row and the SQL query executed.
    """
    if err := _check_capability_id(capability_id):
        return err
    from mcp_server.tools.fetch_user_data import query_sql_user_handler
    return query_sql_user_handler(username)


@mcp.tool(description=_desc("data_mcp", "query_sql_mobile_verification"))
def query_sql_mobile_verification(username: str, capability_id: str = "") -> str:
    """
    Args:
        username:  Username to look up.
        capability_id: Returned by ontology-mcp/get_diagnosis_plan. Required.
    Returns:
        JSON with ismobilenumberverified value and the SQL query executed.
    """
    if err := _check_capability_id(capability_id):
        return err
    from mcp_server.tools.fetch_user_data import query_sql_mobile_handler
    return query_sql_mobile_handler(username)


@mcp.tool(description=_desc("data_mcp", "query_sql_partner_mappings"))
def query_sql_partner_mappings(username: str, capability_id: str = "") -> str:
    """
    Args:
        username:  Username whose partner mappings to fetch.
        capability_id: Returned by ontology-mcp/get_diagnosis_plan. Required.
    Returns:
        JSON with all mapping rows, total count, active count, and SQL query.
    """
    if err := _check_capability_id(capability_id):
        return err
    from mcp_server.tools.fetch_user_data import query_sql_partner_mappings_handler
    return query_sql_partner_mappings_handler(username)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1d  —  MongoDB query
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool(description=_desc("data_mcp", "query_mongo_user"))
def query_mongo_user(username: str, capability_id: str = "") -> str:
    """
    Args:
        username:  Username to look up in MongoDB users collection.
        capability_id: Returned by ontology-mcp/get_diagnosis_plan. Required.
    Returns:
        JSON with projected MongoDB document and the query executed.
    """
    if err := _check_capability_id(capability_id):
        return err
    from mcp_server.tools.fetch_user_data import query_mongo_user_handler
    return query_mongo_user_handler(username)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2  —  SHACL shape validation
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool(description=_desc("data_mcp", "validate_login_shapes"))
def validate_login_shapes(
    username: str,
    capability_id: str = "",
    validation_sequence: str = "",
) -> str:
    """
    Args:
        username:            Username to validate.
        capability_id:       Returned by ontology-mcp/get_diagnosis_plan. Required.
        validation_sequence: Comma-separated shape names from get_diagnosis_plan.
                             Leave empty to run all shapes.
    Returns:
        JSON with per-shape PASS/FAIL, violation messages, and next_step guidance.
    """
    if err := _check_capability_id(capability_id):
        return err
    from mcp_server.tools.validate_shapes import validate_shapes_handler
    shapes = [s.strip() for s in validation_sequence.split(",") if s.strip()] or None
    return validate_shapes_handler(username, shapes)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3  —  New Relic queries (only when all shapes pass)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool(description=_desc("data_mcp", "query_newrelic_login_mfa"))
def query_newrelic_login_mfa(username: str, capability_id: str = "") -> str:
    """
    Args:
        username:  Username to query in New Relic.
        capability_id: Returned by ontology-mcp/get_diagnosis_plan. Required.
    Returns:
        JSON with Transaction rows and Log entries per traceId.
    """
    if err := _check_capability_id(capability_id):
        return err
    from mcp_server.tools.query_newrelic import query_newrelic_login_mfa_handler
    return query_newrelic_login_mfa_handler(username)


@mcp.tool(description=_desc("data_mcp", "query_newrelic_reset_password"))
def query_newrelic_reset_password(
    username: str,
    capability_id: str = "",
    email: str = "",
) -> str:
    """
    Args:
        username:  Username to query across all reset password URIs.
        capability_id: Returned by ontology-mcp/get_diagnosis_plan. Required.
        email:     Email address (optional fallback for RecoverPassword).
    Returns:
        JSON with Transaction rows and Log entries per URI and traceId.
    """
    if err := _check_capability_id(capability_id):
        return err
    from mcp_server.tools.query_newrelic import query_newrelic_reset_password_handler
    return query_newrelic_reset_password_handler(username, email or None)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
