"""
SHACL shape evaluator — programmatic equivalent of running pyshacl at runtime.
Each function below evaluates one shape from login.yaml x_shacl_rules.

Evaluation order (mirrors login.yaml):
  1. LoginBlockShape              — locked / inactive / deleted
  2. SystemUserShape              — system accounts blocked
  3. BuyerSSOShape                — Buyer + SSO blocked
  4. PartnerMappingShape          — no active partner mapping (any user)
  5. SupplierPartnerMappingShape  — Supplier with no valid non-zero BPC
  6. EmailVerificationShape       — valid registered email (reset / OTP flows)
  7. MobileConsistencyShape       — SQL vs MongoDB isMobileNumberVerified mismatch
  8. PartnerMappingDataSyncShape  — SQL vs MongoDB partner mapping field mismatch
"""

import logging
import re
from dataclasses import dataclass, field

from mcp_server.diagnostics.data_fetcher import FetchedData

log = logging.getLogger(__name__)

# Mirrors EmailVerificationShape.constraints[0].pattern in login.yaml.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class ShapeViolation:
    shape_id: str
    message: str
    fields: list[str] = field(default_factory=list)


def evaluate(data: FetchedData) -> list[ShapeViolation]:
    """
    Evaluate all shapes against fetched data.
    Returns a list of ShapeViolation objects (empty list = all shapes pass).
    """
    violations: list[ShapeViolation] = []
    u = data.sql_user
    username = u.get("username", "?")
    partners = data.sql_partner_mappings

    # ── 1. LoginBlockShape ──────────────────────────────────────────────
    if u.get("islocked") == 1:
        violations.append(ShapeViolation(
            "LoginBlockShape",
            f"Account is locked for '{username}'.",
            ["isLocked"],
        ))
    if u.get("isactive") == 0:
        violations.append(ShapeViolation(
            "LoginBlockShape",
            f"Account is deactivated for '{username}'.",
            ["isActive"],
        ))
    if u.get("isdeleted") == 1:
        violations.append(ShapeViolation(
            "LoginBlockShape",
            f"Account is soft-deleted for '{username}'.",
            ["isDeleted"],
        ))

    # ── 2. SystemUserShape ──────────────────────────────────────────────
    if u.get("issystemuser") == 1:
        violations.append(ShapeViolation(
            "SystemUserShape",
            f"'{username}' is a system user — cannot login via the standard flow.",
            ["isSystemUser"],
        ))

    # ── 3. BuyerSSOShape  (userType=0=Buyer, authenticationType=2=SSO) ──
    if u.get("usertype") == 0 and u.get("authenticationtype") == 2:
        violations.append(ShapeViolation(
            "BuyerSSOShape",
            f"Buyer user '{username}' with SSO authentication cannot use the standard login flow.",
            ["userType", "authenticationType"],
        ))

    # ── 4. PartnerMappingShape — no active row for any user ─────────────
    active_partners = [p for p in partners if p.get("isactive") == 1]
    if not active_partners:
        violations.append(ShapeViolation(
            "PartnerMappingShape",
            f"No active partner mapping found for '{username}'.",
            ["mappingIsActive"],
        ))

    # ── 5. SupplierPartnerMappingShape — Supplier(1) + no non-zero BPC ─
    if u.get("usertype") == 1:
        valid_supplier = [p for p in active_partners if p.get("bpc", 0) != 0]
        if not valid_supplier:
            violations.append(ShapeViolation(
                "SupplierPartnerMappingShape",
                f"Supplier '{username}' has no active partner mapping with a valid (non-zero) BPC.",
                ["bpc", "mappingIsActive"],
            ))

    # ── 6. EmailVerificationShape — valid registered email (reset/OTP) ──
    #   Account-active state is deliberately NOT re-checked here; LoginBlockShape
    #   (evaluated above / earlier in the sequence) already covers isActive.
    email = str(u.get("emailaddress") or "").strip()
    if not email or not _EMAIL_PATTERN.match(email):
        violations.append(ShapeViolation(
            "EmailVerificationShape",
            (
                f"No valid registered email address for '{username}' "
                f"(found: {email or 'empty'}) — reset/OTP email cannot be delivered."
            ),
            ["emailAddress"],
        ))

    # ── 7. MobileConsistencyShape ────────────────────────────────────────
    sql_mobile = data.sql_mobile
    mongo_user = data.mongo_user
    if sql_mobile and mongo_user:
        sql_verified = bool(sql_mobile.get("ismobilenumberverified", 0))
        mongo_verified = bool(mongo_user.get("isMobileNumberVerified", False))
        if sql_verified != mongo_verified:
            violations.append(ShapeViolation(
                "MobileConsistencyShape",
                (
                    f"Mobile verification mismatch for '{username}': "
                    f"SQL={sql_verified}, MongoDB={mongo_verified}."
                ),
                ["isMobileNumberVerified"],
            ))

    # ── 8. PartnerMappingDataSyncShape ───────────────────────────────────
    if mongo_user and partners:
        mongo_partners = mongo_user.get("userPartnerMappings", [])
        for sp in partners:
            sp_bpc = sp.get("bpc")
            sp_code = sp.get("partnercode")
            # Find matching MongoDB sub-document by (bpc, partnerCode)
            mp = next(
                (m for m in mongo_partners
                 if m.get("bpc") == sp_bpc and m.get("partnerCode") == sp_code),
                None,
            )
            if mp is None:
                continue
            # Compare isActive (SQL BIT 0/1 vs MongoDB boolean)
            if bool(sp.get("isactive", 0)) != bool(mp.get("isActive", False)):
                violations.append(ShapeViolation(
                    "PartnerMappingDataSyncShape",
                    (
                        f"Partner mapping sync issue (bpc={sp_bpc}, partnerCode={sp_code}): "
                        f"isActive SQL={bool(sp.get('isactive', 0))}, "
                        f"MongoDB={bool(mp.get('isActive', False))}."
                    ),
                    ["mappingIsActive"],
                ))
            # Compare contactCode (stored as BIGINT in SQL, string in MongoDB)
            sql_contact = str(sp.get("contactcode") or "")
            mongo_contact = str(mp.get("contactCode") or "")
            if sql_contact != mongo_contact:
                violations.append(ShapeViolation(
                    "PartnerMappingDataSyncShape",
                    (
                        f"Partner mapping sync issue (bpc={sp_bpc}, partnerCode={sp_code}): "
                        f"contactCode SQL={sp.get('contactcode')}, "
                        f"MongoDB={mp.get('contactCode')}."
                    ),
                    ["contactCode"],
                ))

    return violations
