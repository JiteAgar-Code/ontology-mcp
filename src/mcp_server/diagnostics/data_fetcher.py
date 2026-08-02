"""
DataFetcher — orchestrates SQL Server + MongoDB fetch for a given username.
Returns a unified FetchedData object consumed by the validator and rule engine.
MongoDB is non-fatal: if the connection fails, validation continues with mongo_user=None.
"""

import logging
from dataclasses import dataclass, field

from mcp_server.connectors.sql_connector import SqlConnector
from mcp_server.connectors.mongo_connector import MongoConnector

log = logging.getLogger(__name__)


@dataclass
class FetchedData:
    sql_user: dict = field(default_factory=dict)
    sql_mobile: dict | None = None
    sql_partner_mappings: list[dict] = field(default_factory=list)
    mongo_user: dict | None = None


def fetch_all(username: str) -> tuple["FetchedData | None", "str | None"]:
    """
    Fetch SQL Server and MongoDB data for the given username.

    Returns:
        (FetchedData, None)        — success
        (None, error_message)      — user not found or SQL error
    """
    # ── SQL Server ────────────────────────────────────────────────────────
    try:
        with SqlConnector() as sql:
            sql_user = sql.fetch_user(username)
            if not sql_user:
                return None, f"User '{username}' not found in SQL Server."

            user_id = sql_user.get("userid")
            sql_mobile = sql.fetch_mobile_verification(username)
            sql_partners = sql.fetch_partner_mappings(user_id) if user_id else []

    except Exception as exc:
        log.exception("SQL Server fetch failed for '%s'", username)
        return None, f"SQL Server connection error: {exc}"

    # ── MongoDB ───────────────────────────────────────────────────────────
    mongo_user = None
    try:
        with MongoConnector() as mongo:
            mongo_user = mongo.fetch_user_document(username)
            if mongo_user is None:
                # Fallback: try by email address
                email = sql_user.get("emailaddress")
                if email:
                    mongo_user = mongo.fetch_user_by_email(email)

    except Exception as exc:
        log.warning(
            "MongoDB fetch failed for '%s' (continuing without Mongo data): %s",
            username, exc,
        )

    return FetchedData(
        sql_user=sql_user,
        sql_mobile=sql_mobile,
        sql_partner_mappings=sql_partners,
        mongo_user=mongo_user,
    ), None
