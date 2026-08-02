"""
diagnose_login MCP tool — full diagnostic flow:
  1. Resolve intent from natural-language prompt (KG SPARQL)
  2. Fetch SQL Server + MongoDB data for the username
  3. Evaluate SHACL shapes (programmatic)
  4. Apply decision rules → report violation OR query New Relic
"""

import json
import logging

from mcp_server.diagnostics.data_fetcher import fetch_all
from mcp_server.diagnostics.shacl_validator import evaluate as evaluate_shapes
from mcp_server.diagnostics.rule_engine import evaluate as apply_rules

log = logging.getLogger(__name__)


def diagnose_login_handler(
    username: str,
    intent_id: str,
    fuseki_url: str,
) -> str:
    """
    Args:
        username:   The username (or email address) to diagnose.
        intent_id:  Intent ID resolved from the user's prompt (e.g. 'intent_diagnose_login_failure').
        fuseki_url: Fuseki endpoint URL (passed from server env).

    Returns:
        JSON string with status, rules_fired, diagnoses, and optional newrelic results.
    """
    # ── Step 1: Fetch data ─────────────────────────────────────────────────
    data, error = fetch_all(username)
    if error:
        return json.dumps({
            "status": "error",
            "message": error,
            "username": username,
        }, indent=2)

    # ── Step 2: Evaluate SHACL shapes ─────────────────────────────────────
    violations = evaluate_shapes(data)

    # ── Step 3: Apply decision rules ──────────────────────────────────────
    result = apply_rules(violations, data, intent_id)

    # Attach user summary for context
    u = data.sql_user
    result["user_summary"] = {
        "username":           u.get("username"),
        "email":              u.get("emailaddress"),
        "userType":           u.get("usertype"),
        "authenticationType": u.get("authenticationtype"),
        "isLocked":           u.get("islocked"),
        "isActive":           u.get("isactive"),
        "isDeleted":          u.get("isdeleted"),
        "isSystemUser":       u.get("issystemuser"),
        "mongoFound":         data.mongo_user is not None,
        "partnerMappings":    len(data.sql_partner_mappings),
    }

    return json.dumps(result, indent=2, default=str)
