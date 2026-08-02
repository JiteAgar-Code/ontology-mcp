"""
SQL Server connector — UM_Users, UM_UserMobileNumberVerified, UM_UserPartnermapping.
Reads connection config from environment variables (see .env.example).
"""

import os
import logging
import pyodbc

log = logging.getLogger(__name__)

_PREFERRED_DRIVERS = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server",
]


def _pick_driver() -> str:
    available = pyodbc.drivers()
    for d in _PREFERRED_DRIVERS:
        if d in available:
            return d
    if available:
        return available[0]
    raise RuntimeError("No ODBC SQL Server driver found. Install 'ODBC Driver 17/18 for SQL Server'.")


def _build_connection_string() -> str:
    driver = _pick_driver()
    host = os.environ["SQL_SERVER_HOST"]
    port = os.environ.get("SQL_SERVER_PORT", "").strip()
    database = os.environ["SQL_SERVER_DATABASE"]
    trusted = os.environ.get("SQL_SERVER_TRUSTED_CONNECTION", "").lower() in ("yes", "true", "1")
    encrypt = os.environ.get("SQL_SERVER_ENCRYPT", "yes")
    trust_cert = os.environ.get("SQL_SERVER_TRUST_CERT", "no")

    # LocalDB and named instances use named pipes — no port suffix
    server = f"{host},{port}" if port else host

    extra = f"Encrypt={encrypt};TrustServerCertificate={trust_cert};"

    if trusted:
        return (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"Trusted_Connection=yes;"
            f"{extra}"
        )

    username = os.environ["SQL_SERVER_USERNAME"]
    password = os.environ["SQL_SERVER_PASSWORD"]
    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"{extra}"
    )


class SqlConnector:
    """
    Context-manager wrapper around a single pyodbc connection.
    One instance per request — do not share across threads.

    Usage:
        with SqlConnector() as sql:
            user = sql.fetch_user("jdoe")
    """

    def __init__(self):
        self._conn = None

    def connect(self) -> "SqlConnector":
        conn_str = _build_connection_string()
        self._conn = pyodbc.connect(conn_str, timeout=15)
        log.debug("SQL Server connection opened")
        return self

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
            log.debug("SQL Server connection closed")

    def __enter__(self) -> "SqlConnector":
        return self.connect()

    def __exit__(self, *_):
        self.close()

    # ── helpers ──────────────────────────────────────────────────────────

    def _fetchall(self, sql: str, *params) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute(sql, *params)
        columns = [c[0].lower() for c in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    # ── public queries ────────────────────────────────────────────────────

    def fetch_user(self, username: str) -> dict | None:
        rows = self._fetchall(
            """
            SELECT userid, username, emailaddress, firstname, lastname,
                   usertype, authenticationtype,
                   islocked, isactive, isdeleted, issystemuser,
                   isdcode, mobileno
            FROM   UM_Users
            WHERE  username = ?
            """,
            username,
        )
        return rows[0] if rows else None

    def fetch_mobile_verification(self, username: str) -> dict | None:
        rows = self._fetchall(
            """
            SELECT username, ismobilenumberverified
            FROM   UM_UserMobileNumberVerified
            WHERE  username = ?
            """,
            username,
        )
        return rows[0] if rows else None

    def fetch_partner_mappings(self, user_id: int) -> list[dict]:
        return self._fetchall(
            """
            SELECT userid, bpc, partnercode, isactive, contactcode
            FROM   UM_UserPartnermapping
            WHERE  userid = ?
            """,
            user_id,
        )
