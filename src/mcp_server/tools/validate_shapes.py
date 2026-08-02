"""
validate_login_shapes — Step 2 of the diagnostic flow.
Evaluates SHACL shapes against live SQL + MongoDB data and returns per-shape
pass/fail with violation details, plus an advisory email-mismatch check (dr_012).
"""

import json
from mcp_server.diagnostics.data_fetcher import fetch_all
from mcp_server.diagnostics.shacl_validator import evaluate

_ALL_SHAPES = [
    "LoginBlockShape",
    "SystemUserShape",
    "BuyerSSOShape",
    "PartnerMappingShape",
    "SupplierPartnerMappingShape",
    "EmailVerificationShape",
    "MobileConsistencyShape",
    "PartnerMappingDataSyncShape",
]

_SHAPE_TO_RULE = {
    "LoginBlockShape":             "dr_003",
    "SystemUserShape":             "dr_005",
    "BuyerSSOShape":               "dr_006",
    "PartnerMappingShape":         "dr_004",
    "SupplierPartnerMappingShape": "dr_007",
    "EmailVerificationShape":      None,      # validation shape, no dedicated rule
    "MobileConsistencyShape":      "dr_002",
    "PartnerMappingDataSyncShape": "dr_008",
}


def _email_mismatch_advisory(input_identifier: str, sql_user: dict) -> dict | None:
    """
    dr_012 (advisory): fire only when the identifier the user provided looks like
    an email (contains '@') AND differs from the registered emailAddress.
    A username that legitimately differs from the email does NOT trigger this.
    """
    if "@" not in (input_identifier or ""):
        return None
    registered = str(sql_user.get("emailaddress") or "").strip()
    if not registered:
        return None
    if input_identifier.strip().lower() == registered.lower():
        return None
    return {
        "rule":     "dr_012",
        "severity": "advisory",
        "message": (
            f"Email mismatch: the query used '{input_identifier}', but the "
            f"registered email on the account is '{registered}'. A reset/OTP email "
            f"would be delivered to '{registered}', not the queried address. "
            f"Confirm whether the correct account is being investigated."
        ),
        "fields": {"input_identifier": input_identifier, "registered_email": registered},
    }


def validate_shapes_handler(username: str, shapes_filter: list[str] | None = None) -> str:
    data, error = fetch_all(username)
    if error:
        return json.dumps({"status": "error", "message": error, "username": username}, indent=2)

    violations = evaluate(data)

    # Only report on shapes in the validation_sequence (if provided by the plan)
    shapes_to_report = shapes_filter if shapes_filter else _ALL_SHAPES
    shapes_result = []
    for shape in shapes_to_report:
        shape_violations = [v for v in violations if v.shape_id == shape]
        if shape_violations:
            shapes_result.append({
                "shape":      shape,
                "status":     "FAIL",
                "rule":       _SHAPE_TO_RULE.get(shape),
                "violations": [{"message": v.message, "fields": v.fields} for v in shape_violations],
            })
        else:
            shapes_result.append({
                "shape":  shape,
                "status": "PASS",
            })

    # all_shapes_pass counts ONLY the shapes in scope (not shapes outside the plan)
    reported_fail = any(s["status"] == "FAIL" for s in shapes_result)

    # Advisory (does NOT affect all_shapes_pass — it is informational)
    advisories = []
    adv = _email_mismatch_advisory(username, data.sql_user)
    if adv:
        advisories.append(adv)

    return json.dumps({
        "status":          "ok",
        "username":        username,
        "all_shapes_pass": not reported_fail,
        "shapes":          shapes_result,
        "violation_count": sum(len(s.get("violations", [])) for s in shapes_result),
        "advisories":      advisories,
        "next_step": (
            "All in-scope data checks passed. If the plan's newrelic_tool is not "
            "null, call it (query_newrelic_login_mfa or query_newrelic_reset_password). "
            "Report any advisories alongside your findings."
            if not reported_fail
            else "Violations found above. Report them (with the mapped rule) and any "
                 "advisories. Do NOT call New Relic."
        ),
    }, indent=2)
