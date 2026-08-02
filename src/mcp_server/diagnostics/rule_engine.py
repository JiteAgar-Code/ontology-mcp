"""
Rule engine — maps SHACL shape violations to decision rules (dr_002..dr_008),
or dispatches to New Relic when all shapes pass (dr_001, dr_010, dr_011).
Rule IDs mirror login.yaml x_decision_rules.
"""

import logging

from mcp_server.diagnostics.data_fetcher import FetchedData
from mcp_server.diagnostics.shacl_validator import ShapeViolation
from mcp_server.connectors.newrelic_connector import NewRelicConnector

log = logging.getLogger(__name__)

# Shape → decision rule ID (login.yaml x_decision_rules)
_SHAPE_TO_RULE: dict[str, str] = {
    "MobileConsistencyShape":      "dr_002",
    "LoginBlockShape":             "dr_003",
    "PartnerMappingShape":         "dr_004",
    "SystemUserShape":             "dr_005",
    "BuyerSSOShape":               "dr_006",
    "SupplierPartnerMappingShape": "dr_007",
    "PartnerMappingDataSyncShape": "dr_008",
}

_MFA_INTENTS   = {"intent_diagnose_login_failure", "intent_diagnose_sms_otp"}
_RESET_INTENTS = {"intent_diagnose_reset_password_link", "intent_diagnose_otp_email"}


def evaluate(
    violations: list[ShapeViolation],
    data: FetchedData,
    intent_id: str,
) -> dict:
    """
    Apply decision rules to shape violations and, if none, query New Relic.

    Returns:
        {
          "status":      "violation" | "newrelic" | "newrelic_error",
          "rules_fired": [{"rule": "dr_XXX", "shape": "...", "message": "..."}],
          "diagnoses":   ["..."],          # present when status="violation"
          "newrelic":    {...}             # present when status="newrelic"
          "error":       "..."            # present when status="newrelic_error"
        }
    """
    if violations:
        return _report_violations(violations)
    return _query_newrelic(data, intent_id)


# ── violation path ────────────────────────────────────────────────────────────

def _report_violations(violations: list[ShapeViolation]) -> dict:
    rules_fired = []
    diagnoses = []
    for v in violations:
        rule_id = _SHAPE_TO_RULE.get(v.shape_id, "unknown")
        rules_fired.append({
            "rule":    rule_id,
            "shape":   v.shape_id,
            "message": v.message,
            "fields":  v.fields,
        })
        diagnoses.append(v.message)
    return {"status": "violation", "rules_fired": rules_fired, "diagnoses": diagnoses}


# ── New Relic path ────────────────────────────────────────────────────────────

def _query_newrelic(data: FetchedData, intent_id: str) -> dict:
    username = data.sql_user.get("username", "")
    email    = data.sql_user.get("emailaddress")
    nr = NewRelicConnector()

    try:
        if intent_id in _MFA_INTENTS:
            result = nr.diagnose_login_mfa(username)
            rule   = "dr_010"
        elif intent_id in _RESET_INTENTS:
            result = nr.diagnose_reset_password(username, email)
            rule   = "dr_011"
        else:
            result = nr.query_generic(username)
            rule   = "dr_001"

        return {
            "status":      "newrelic",
            "rules_fired": [{"rule": rule}],
            "newrelic":    result,
        }

    except Exception as exc:
        log.exception("New Relic query failed for '%s' (intent=%s)", username, intent_id)
        return {
            "status":      "newrelic_error",
            "rules_fired": [],
            "error":       str(exc),
        }
