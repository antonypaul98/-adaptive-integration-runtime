"""Persisted target-bound final human approval; never deployment execution authority."""
from hashlib import sha256
import json
import re

from .approval_review import prepare_review
from .postgres import canonical_json
from .repair_proposal import reference

VERSION = "air-final-approval-v1"
PURPOSE = "FINAL_APPROVAL_NO_DEPLOYMENT_EXECUTION"


class FinalApprovalError(ValueError):
    pass


def _bounded_text(value, name, limit=256):
    if (type(value) is not str or not value.strip() or len(value) > limit
            or any(ord(c) < 32 for c in value)):
        raise FinalApprovalError("invalid_" + name)
    return value.strip()


def _scope(value):
    """Canonical bounded declarative target scope; never executable instructions."""
    if not isinstance(value, dict) or not value or len(value) > 32:
        raise FinalApprovalError("invalid_scope")
    normalized = {}
    for key, item in value.items():
        key = _bounded_text(key, "scope", 128)
        if type(item) not in (str, int, bool):
            raise FinalApprovalError("invalid_scope")
        if isinstance(item, str):
            item = _bounded_text(item, "scope", 1024)
        normalized[key] = item
    encoded = canonical_json(normalized)
    if len(encoded.encode("utf-8")) > 16384:
        raise FinalApprovalError("scope_limit")
    return json.loads(encoded)


def approve(tx, proposal_id, *, proposal_hash, revision, current_impact_id,
            verification_id, verification_hash, fixture_hash, review_hash,
            environment, integration_id, scope, confirmed=False):
    """Persist exact human approval for one target/scope, without execution authority.

    The read-only review is recomputed inside this transaction so stale, superseded,
    cross-tenant, substituted-fixture or otherwise mismatched evidence fails closed.
    Reviewer identity comes only from the administrator-provisioned database login.
    """
    if confirmed is not True:
        raise FinalApprovalError("explicit_human_approval_required")
    if type(review_hash) is not str or not re.fullmatch(r"[0-9a-f]{64}", review_hash):
        raise FinalApprovalError("invalid_review_hash")
    review = prepare_review(
        tx, proposal_id, proposal_hash=proposal_hash, revision=revision,
        current_impact_id=current_impact_id, verification_id=verification_id,
        verification_hash=verification_hash, fixture_hash=fixture_hash)
    if review.content_hash != review_hash:
        raise FinalApprovalError("review_binding_mismatch")
    body = json.loads(review.payload)
    impact_target = body["impact_item"]["dependency"]
    if _bounded_text(integration_id, "integration_id", 256) != str(impact_target["integration_id"]):
        raise FinalApprovalError("integration_target_mismatch")
    reviewer = tx._connection.execute(
        "SELECT air.current_reviewer() AS reviewer").fetchone()["reviewer"]
    payload = {
        "final_approval_version": VERSION,
        "purpose": PURPOSE,
        "tenant_id": str(tx.tenant_id),
        "proposal": body["proposal"],
        "revision": revision,
        "prior_proposal_decision": body["prior_proposal_decision"],
        "impact": body["impact"],
        "change_evidence": body["change_evidence"],
        "sandbox": body["sandbox"],
        "verification": body["verification"],
        "fixture_hash": fixture_hash,
        "review_hash": review_hash,
        "review_payload": review.payload,
        "confirmed": True,
        "target": {
            "environment": _bounded_text(environment, "environment", 128),
            "integration_id": str(impact_target["integration_id"]),
            "mapping_id": str(impact_target["mapping_id"]),
            "scope": _scope(scope),
        },
        "reviewer": reviewer,
    }
    key = sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return tx.put("final_approval", key, payload)


def load_final_approval(tx, identity):
    try:
        record = tx.get_by_id(identity, kind="final_approval")
    except (ValueError, TypeError):
        record = None
    if record is None or record["tenant_id"] != tx.tenant_id:
        raise FinalApprovalError("not_found_or_not_authorized")
    try:
        payload = json.loads(record["payload"])
    except (TypeError, json.JSONDecodeError):
        raise FinalApprovalError("integrity_failure") from None
    if (payload.get("tenant_id") != str(tx.tenant_id)
            or payload.get("purpose") != PURPOSE
            or payload.get("final_approval_version") != VERSION
            or sha256(record["payload"].encode("utf-8")).hexdigest() != record["content_hash"]):
        raise FinalApprovalError("integrity_failure")
    return record
