"""
New Relic connector — NRQL via NerdGraph GraphQL API.

Two-step query flow (per login.yaml dr_010 / dr_011):
  Step 1: query Transaction table by username + URI filter → get traceId + timestamp
  Step 2: query Log table WHERE trace.id = traceId SINCE <transaction_timestamp>

Max lookback: 7 days (enforced in all NRQL templates).
Reads config from environment variables (see .env.example).
"""

import os
import json
import logging
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

_NERDGRAPH_URL = {
    "US": "https://api.newrelic.com/graphql",
    "EU": "https://api.eu.newrelic.com/graphql",
}

_NRQL_GRAPHQL = """
{{
  actor {{
    account(id: {account_id}) {{
      nrql(query: {nrql_json}) {{
        results
      }}
    }}
  }}
}}
"""


class NewRelicConnector:
    """
    Executes NRQL queries through the NerdGraph GraphQL endpoint.

    dr_010 — diagnose_login_mfa()       → /Account/Login two-step
    dr_011 — diagnose_reset_password()  → three URIs two-step each
    dr_001 — query_generic()            → generic Log fallback
    """

    def __init__(self):
        self.api_key = os.environ["NEW_RELIC_API_KEY"]
        self.account_id = os.environ["NEW_RELIC_ACCOUNT_ID"]
        region = os.environ.get("NEW_RELIC_REGION", "US").upper()
        self.endpoint = _NERDGRAPH_URL.get(region, _NERDGRAPH_URL["US"])
        self.env = os.environ.get("APP_ENV", "")

    # ── core NRQL executor ────────────────────────────────────────────────

    def query_nrql(self, nrql: str) -> list[dict]:
        """Execute one NRQL statement and return the result rows list."""
        payload = {"query": _NRQL_GRAPHQL.format(
            account_id=self.account_id,
            nrql_json=json.dumps(nrql),
        )}
        headers = {
            "Content-Type": "application/json",
            "Api-Key": self.api_key,
        }
        resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        try:
            return body["data"]["actor"]["account"]["nrql"]["results"]
        except (KeyError, TypeError):
            log.warning("Unexpected NerdGraph response: %s", body)
            return []

    # ── helpers ───────────────────────────────────────────────────────────

    def _since_from_tx(self, tx: dict) -> str:
        """
        Derive the SINCE clause for the Log query from a transaction row's timestamp.
        New Relic timestamps are epoch milliseconds; NRQL SINCE accepts ISO-like strings.
        """
        ts = tx.get("timestamp")
        if ts:
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S +0000")
        return "7 days ago"

    def _fetch_logs_for_tx(self, tx: dict) -> list[dict]:
        """Step 2: query Log by traceId derived from a transaction row."""
        trace_id = tx.get("traceId")
        if not trace_id:
            return []
        since = self._since_from_tx(tx)
        nrql = (
            f"SELECT * FROM Log "
            f"WHERE `trace.id` = '{trace_id}' "
            f"SINCE '{since}' "
            f"LIMIT MAX"
        )
        return self.query_nrql(nrql)

    def _two_step(self, uri: str, step1_nrql: str) -> dict:
        """Run step-1 Transaction query then step-2 Log query per traceId."""
        transactions = self.query_nrql(step1_nrql)
        logs = [
            {"traceId": tx.get("traceId"), "logs": self._fetch_logs_for_tx(tx)}
            for tx in transactions
            if tx.get("traceId")
        ]
        return {
            "uri": uri,
            "found": bool(transactions),
            "transactions": transactions,
            "logs": logs,
        }

    # ── dr_010: Login / MFA ───────────────────────────────────────────────

    def diagnose_login_mfa(self, username: str) -> dict:
        """
        Two-step query for /Account/Login.
        Transaction columns: LoginUserName, traceId, RequiresTwoFactor, TwoFactorDetails.
        """
        nrql = (
            f"SELECT LoginUserName, traceId, RequiresTwoFactor, TwoFactorDetails "
            f"FROM Transaction "
            f"WHERE request.uri LIKE '%/Account/Login%' "
            f"AND appName LIKE '%{self.env}%' "
            f"AND LoginUserName = '{username}' "
            f"SINCE 7 days ago LIMIT MAX"
        )
        return self._two_step("/Account/Login", nrql)

    # ── dr_011: Reset password (3 URIs) ──────────────────────────────────

    def diagnose_reset_password(self, username: str, email: str | None) -> dict:
        """
        Two-step query for all three reset password URIs.
        Returns a dict keyed by URI slug.
        """
        # /Account/RecoverPassword — use username OR email
        email_clause = f"OR RecoveryEmail = '{email}' " if email else ""
        recover_nrql = (
            f"SELECT traceId, errorMessage, RecoveryUserName, RecoveryEmail "
            f"FROM Transaction "
            f"WHERE request.uri LIKE '%/Account/RecoverPassword%' "
            f"AND appName LIKE '%{self.env}%' "
            f"AND (RecoveryUserName = '{username}' {email_clause}) "
            f"SINCE 7 days ago LIMIT MAX"
        )

        # /Account/PreResetPassword
        pre_reset_nrql = (
            f"SELECT traceId, errorMessage, PreResetUserName "
            f"FROM Transaction "
            f"WHERE request.uri LIKE '%/Account/PreResetPassword%' "
            f"AND appName LIKE '%{self.env}%' "
            f"AND PreResetUserName = '{username}' "
            f"SINCE 7 days ago LIMIT MAX"
        )

        # /Account/ResetPassword
        reset_nrql = (
            f"SELECT LoginUserName, traceId, errorMessage "
            f"FROM Transaction "
            f"WHERE request.uri LIKE '%/Account/ResetPassword%' "
            f"AND appName LIKE '%{self.env}%' "
            f"AND LoginUserName = '{username}' "
            f"SINCE 7 days ago LIMIT MAX"
        )

        return {
            "recover_password":  self._two_step("/Account/RecoverPassword",  recover_nrql),
            "pre_reset_password": self._two_step("/Account/PreResetPassword", pre_reset_nrql),
            "reset_password":    self._two_step("/Account/ResetPassword",    reset_nrql),
        }

    # ── dr_001: generic fallback ──────────────────────────────────────────

    def query_generic(self, username: str) -> list[dict]:
        nrql = (
            f"SELECT * FROM Log "
            f"WHERE username = '{username}' "
            f"SINCE 7 days ago LIMIT MAX"
        )
        return self.query_nrql(nrql)
