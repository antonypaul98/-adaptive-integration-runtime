"""Append-only single-use execution outcome evidence; never an executor.

This module records a bounded caller-supplied result after an external executor
has independently revalidated an accepted plan and target state. Recording an
outcome requires the exact persisted pre-execution claim, closing the sequence
without turning either artifact into execution authority. It contains no
transport, command, callback, credentials, or ability to perform deployment.
"""
from hashlib import sha256
import json
import re
from uuid import UUID

from .execution_claim import ExecutionClaimError, load_execution_claim
from .execution_plan import (
    ExecutionPlan,
    PURPOSE as PLAN_PURPOSE,
    VERSION as PLAN_VERSION,
)
from .postgres import IdempotencyConflict, canonical_json

VERSION = "air-execution-outcome-v1"
PURPOSE = "APPEND_ONLY_OUTCOME_EVIDENCE_NO_DEPLOYMENT_EXECUTION"
STATUSES = frozenset({"succeeded", "failed", "aborted"})
_HASH = re.compile(r"[0-9a-f]{64}")
_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}")


class ExecutionOutcomeError(ValueError):
    pass


def _hash(value, name):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ExecutionOutcomeError("invalid_" + name)
    return value


def record_execution_outcome(tx, plan, *, claim_id, plan_hash,
                             observed_target_state_hash, status, outcome_hash,
                             reason_code):
    """Persist exactly one immutable result per plan, with safe idempotent retry.

    A repeated byte-identical outcome returns the existing evidence. Any attempt
    to reuse the same plan for a different outcome fails closed through the
    transaction's immutable idempotency key.
    """
    try:
        if not isinstance(plan, ExecutionPlan):
            raise ExecutionOutcomeError("invalid_plan")
        plan_hash = _hash(plan_hash, "plan_hash")
        observed_target_state_hash = _hash(
            observed_target_state_hash, "observed_target_state_hash")
        outcome_hash = _hash(outcome_hash, "outcome_hash")
        if plan.content_hash != plan_hash:
            raise ExecutionOutcomeError("plan_hash_mismatch")
        claim = load_execution_claim(tx, claim_id)
        claim_body = json.loads(claim["payload"])
        if type(status) is not str or status not in STATUSES:
            raise ExecutionOutcomeError("invalid_status")
        if type(reason_code) is not str or _REASON.fullmatch(reason_code) is None:
            raise ExecutionOutcomeError("invalid_reason_code")
        body = json.loads(plan.payload)
        required = {
            "revalidate_boundary": True,
            "revalidate_target_state_hash": True,
            "single_use": True,
            "append_only_outcome_evidence": True,
        }
        if (not isinstance(body, dict)
                or body.get("version") != PLAN_VERSION
                or body.get("purpose") != PLAN_PURPOSE
                or body.get("tenant_id") != str(tx.tenant_id)
                or body.get("target_state_hash") != observed_target_state_hash
                or body.get("executor_requirements") != required
                or type(body.get("revision")) is not int
                or body["revision"] < 1):
            raise ExecutionOutcomeError("plan_or_target_mismatch")
        for name in ("approval", "proposal", "verification", "target"):
            if not isinstance(body.get(name), dict) or not body[name]:
                raise ExecutionOutcomeError("invalid_plan")
        if (claim_body.get("plan_hash") != plan_hash
                or claim_body.get("boundary_hash") != body["boundary_hash"]
                or claim_body.get("observed_target_state_hash")
                != observed_target_state_hash
                or claim_body.get("approval") != body["approval"]
                or claim_body.get("proposal") != body["proposal"]
                or claim_body.get("revision") != body["revision"]
                or claim_body.get("verification") != body["verification"]
                or claim_body.get("review_hash") != body.get("review_hash")
                or claim_body.get("target") != body["target"]):
            raise ExecutionOutcomeError("claim_plan_mismatch")
        payload = {
            "version": VERSION,
            "purpose": PURPOSE,
            "tenant_id": str(tx.tenant_id),
            "plan_hash": plan_hash,
            "boundary_hash": body["boundary_hash"],
            "observed_target_state_hash": observed_target_state_hash,
            "approval": body["approval"],
            "proposal": body["proposal"],
            "revision": body["revision"],
            "verification": body["verification"],
            "review_hash": body.get("review_hash"),
            "target": body["target"],
            "claim": {
                "artifact_id": str(claim["artifact_id"]),
                "artifact_hash": claim["content_hash"],
                "executor_identity_hash": claim_body["executor_identity_hash"],
                "claim_nonce_hash": claim_body["claim_nonce_hash"],
            },
            "status": status,
            "outcome_hash": outcome_hash,
            "reason_code": reason_code,
        }
        return tx.put("execution_outcome", plan_hash, payload)
    except IdempotencyConflict as exc:
        raise ExecutionOutcomeError("plan_already_consumed") from exc
    except ExecutionClaimError as exc:
        raise ExecutionOutcomeError("claim_not_found_or_invalid") from exc
    except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError) as exc:
        if isinstance(exc, ExecutionOutcomeError):
            raise
        raise ExecutionOutcomeError("execution_outcome_rejected") from exc


def load_execution_outcome(tx, identity):
    """Reload and verify immutable tenant-bound outcome evidence."""
    try:
        record = tx.get_by_id(identity, kind="execution_outcome")
    except (ValueError, TypeError):
        record = None
    if record is None or record["tenant_id"] != tx.tenant_id:
        raise ExecutionOutcomeError("not_found_or_not_authorized")
    try:
        payload = json.loads(record["payload"])
    except (TypeError, json.JSONDecodeError):
        raise ExecutionOutcomeError("integrity_failure") from None
    if (payload.get("version") != VERSION
            or payload.get("purpose") != PURPOSE
            or payload.get("tenant_id") != str(tx.tenant_id)
            or payload.get("plan_hash") != record["idempotency_key"]
            or sha256(record["payload"].encode("utf-8")).hexdigest()
            != record["content_hash"]):
        raise ExecutionOutcomeError("integrity_failure")
    claim = payload.get("claim")
    try:
        UUID(claim["artifact_id"])
    except (KeyError, TypeError, ValueError):
        raise ExecutionOutcomeError("integrity_failure") from None
    for name in ("artifact_hash", "executor_identity_hash", "claim_nonce_hash"):
        if type(claim.get(name)) is not str or _HASH.fullmatch(claim[name]) is None:
            raise ExecutionOutcomeError("integrity_failure")
    return record
