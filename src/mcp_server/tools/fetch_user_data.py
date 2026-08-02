"""
Individual data-fetch tools — one tool per database query.
Each appears as a separate visible tool call in the agent UI.
"""

import json
from mcp_server.connectors.sql_connector import SqlConnector
from mcp_server.connectors.mongo_connector import MongoConnector


def _sql_error(exc: Exception, query: str) -> str:
    return json.dumps({"status": "error", "query": query, "error": str(exc)}, indent=2)


def query_sql_user_handler(username: str) -> str:
    """SELECT from UM_Users WHERE username = ?"""
    try:
        with SqlConnector() as sql:
            row = sql.fetch_user(username)
        return json.dumps({
            "status": "ok",
            "table": "UM_Users",
            "query": f"SELECT * FROM UM_Users WHERE username = '{username}'",
            "row": row,
        }, indent=2, default=str)
    except Exception as exc:
        return _sql_error(exc, "UM_Users")


def query_sql_mobile_handler(username: str) -> str:
    """SELECT from UM_UserMobileNumberVerified WHERE username = ?"""
    try:
        with SqlConnector() as sql:
            row = sql.fetch_mobile_verification(username)
        return json.dumps({
            "status": "ok",
            "table": "UM_UserMobileNumberVerified",
            "query": f"SELECT * FROM UM_UserMobileNumberVerified WHERE username = '{username}'",
            "row": row,
        }, indent=2, default=str)
    except Exception as exc:
        return _sql_error(exc, "UM_UserMobileNumberVerified")


def query_sql_partner_mappings_handler(username: str) -> str:
    """SELECT from UM_UserPartnermapping WHERE userid = (looked up from UM_Users)"""
    try:
        with SqlConnector() as sql:
            user = sql.fetch_user(username)
            if not user:
                return json.dumps({
                    "status": "error",
                    "table": "UM_UserPartnermapping",
                    "error": f"User '{username}' not found in UM_Users — cannot fetch partner mappings.",
                }, indent=2)
            user_id = user.get("userid")
            rows = sql.fetch_partner_mappings(user_id)
        return json.dumps({
            "status": "ok",
            "table": "UM_UserPartnermapping",
            "query": f"SELECT * FROM UM_UserPartnermapping WHERE userid = {user_id}",
            "userid": user_id,
            "rows": rows,
            "total": len(rows),
            "active": sum(1 for r in rows if r.get("isactive") == 1),
        }, indent=2, default=str)
    except Exception as exc:
        return _sql_error(exc, "UM_UserPartnermapping")


_MONGO_PROJECTION_DISPLAY = (
    "{ userName, emailAddress, userType, authenticationType, "
    "isActive, isLocked, isSystemUser, isMobileNumberVerified, userPartnerMappings }"
)

def query_mongo_user_handler(username: str) -> str:
    """db.users.find_one({ userName / normalizedUserName: username }, <diagnostic projection>)"""
    try:
        with MongoConnector() as mongo:
            doc = mongo.fetch_user_document(username)
        return json.dumps({
            "status":     "ok",
            "collection": "users",
            "query":      (
                f"db.users.find_one("
                f"{{ $or: [{{userName: '{username}'}}, {{normalizedUserName: '{username.lower()}'}}] }}, "
                f"{_MONGO_PROJECTION_DISPLAY})"
            ),
            "found":      doc is not None,
            "document":   doc,
        }, indent=2, default=str)
    except Exception as exc:
        return json.dumps({"status": "error", "collection": "users", "error": str(exc)}, indent=2)


# ── legacy combined handler (kept for diagnose_login backward compat) ──────────

from mcp_server.diagnostics.data_fetcher import fetch_all

def fetch_user_data_handler(username: str) -> str:
    data, error = fetch_all(username)
    if error:
        return json.dumps({"status": "error", "message": error, "username": username}, indent=2)
    return json.dumps({
        "status": "ok",
        "username": username,
        "sql_user": data.sql_user,
        "sql_mobile": data.sql_mobile,
        "sql_partner_mappings": data.sql_partner_mappings,
        "mongo_user": data.mongo_user,
    }, indent=2, default=str)
