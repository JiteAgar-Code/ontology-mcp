"""
MongoDB connector — users collection.
Reads connection config from environment variables (see .env.example).
"""

import os
import logging
from pymongo import MongoClient
from pymongo.collection import Collection

log = logging.getLogger(__name__)


class MongoConnector:
    """
    Context-manager wrapper around a pymongo MongoClient.
    One instance per request.

    Usage:
        with MongoConnector() as mongo:
            doc = mongo.fetch_user_document("jdoe")
    """

    def __init__(self):
        self._client = None
        self._db = None

    def connect(self) -> "MongoConnector":
        uri = os.environ["MONGODB_URI"]
        db_name = os.environ["MONGODB_DATABASE"]
        self._client = MongoClient(uri, serverSelectionTimeoutMS=10_000)
        self._db = self._client[db_name]
        log.debug("MongoDB connection opened (db=%s)", db_name)
        return self

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
            log.debug("MongoDB connection closed")

    def __enter__(self) -> "MongoConnector":
        return self.connect()

    def __exit__(self, *_):
        self.close()

    # ── collection accessor ───────────────────────────────────────────────

    def _users(self) -> Collection:
        return self._db["users"]

    # ── public queries ────────────────────────────────────────────────────

    # Fields required for SHACL shape validation and cross-source checks.
    # Normalized/derived fields and display-only fields are excluded.
    _DIAGNOSTIC_PROJECTION = {
        "_id":                   0,
        "userName":              1,
        "emailAddress":          1,
        "userType":              1,
        "authenticationType":    1,
        "isActive":              1,
        "isLocked":              1,
        "isSystemUser":          1,
        "isMobileNumberVerified": 1,
        "userPartnerMappings":   1,   # sub-fields: bpc, partnerCode, isActive, contactCode
    }

    def fetch_user_document(self, username: str) -> dict | None:
        """
        Look up by userName (exact) or normalizedUserName (lowercase fallback).
        Returns only diagnostic fields — not the full document.
        """
        return self._users().find_one(
            {"$or": [
                {"userName": username},
                {"normalizedUserName": username.lower()},
            ]},
            self._DIAGNOSTIC_PROJECTION,
        )

    def fetch_user_by_email(self, email: str) -> dict | None:
        """Fallback lookup by emailAddress or its normalized form."""
        return self._users().find_one(
            {"$or": [
                {"emailAddress": email},
                {"normalizedEmailAddress": email.lower()},
            ]},
            self._DIAGNOSTIC_PROJECTION,
        )
