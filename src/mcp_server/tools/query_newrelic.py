"""
New Relic query tools — Step 3 of the diagnostic flow.
Called only after validate_login_shapes confirms all shapes pass.

query_newrelic_login_mfa      — dr_010: /Account/Login two-step
query_newrelic_reset_password — dr_011: three reset password URIs two-step
"""

import json
from mcp_server.connectors.newrelic_connector import NewRelicConnector


def query_newrelic_login_mfa_handler(username: str) -> str:
    """
    dr_010: Two-step New Relic query for login / MFA / SMS OTP issues.
    Step 1 — Transaction table: LoginUserName, traceId, RequiresTwoFactor, TwoFactorDetails.
    Step 2 — Log table: domain, failureReason, smsReason per traceId.
    Max lookback: 7 days.
    """
    try:
        nr = NewRelicConnector()
        result = nr.diagnose_login_mfa(username)
        return json.dumps({
            "status":  "ok",
            "rule":    "dr_010",
            "uri":     "/Account/Login",
            "result":  result,
        }, indent=2, default=str)
    except Exception as exc:
        return json.dumps({"status": "error", "rule": "dr_010", "error": str(exc)}, indent=2)


def query_newrelic_reset_password_handler(username: str, email: str | None) -> str:
    """
    dr_011: Two-step New Relic query for reset password issues across three URIs:
      /Account/RecoverPassword  — was reset email triggered?
      /Account/PreResetPassword — did user open the link?
      /Account/ResetPassword    — did the reset form complete?
    Max lookback: 7 days.
    """
    try:
        nr = NewRelicConnector()
        result = nr.diagnose_reset_password(username, email)
        return json.dumps({
            "status": "ok",
            "rule":   "dr_011",
            "uris":   ["/Account/RecoverPassword", "/Account/PreResetPassword", "/Account/ResetPassword"],
            "result": result,
        }, indent=2, default=str)
    except Exception as exc:
        return json.dumps({"status": "error", "rule": "dr_011", "error": str(exc)}, indent=2)
