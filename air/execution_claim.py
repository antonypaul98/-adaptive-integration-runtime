"""Append-only pre-execution single-use claim; never an executor.

An external executor must create this claim after independently revalidating the
accepted plan and authoritative target state, and before taking any consequential
action. The immutable plan-hash key admits one claimant only. This module has no
clock, lease takeover, command, transport, callback, credential, or deployment
capability.
"""
from hashlib import sha256
import json
import re

from .execution_plan import (
    ExecutionPlan,
    PURPOSE as PLAN_PURPOSE,
    VERSION as PLAN_VERSION,
)
from .postgres import IdempotencyConflict, canonical_json

VERSION = "air-execution-claim-v1"
PURPOSE = "APPEND_ONLY_SINGLE_USE_CLAIM_NO_DEPLOYMENT_EXECUTION"
_HASH = re.compile(r"[0-9a-f]{64}")


class ExecutionClaimError(ValueError):
    pass


def _hash(value, name):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ExecutionClaimError("invalid_" + name)
    return value


def claim_execution(tx, plan, *, plan_hash, observed_target_state_hash,
                    executor_identity_hash, claim_nonce_hash):
    """Atomically reserve one exact plan before any external execution.

    A byte-identical retry returns the original claim. A different claimant or
    nonce for the same plan fails closed; claims never expire or transfer.
    """
    try:
        if not isinstance(plan, ExecutionPlan):
            raise ExecutionClaimError("invalid_plan")
        plan_hash = _hash(plan_hash, "plan_hash")
        observed_target_state_hash = _hash(
            observed_target_state_hash, "observed_target_state_hash")
        executor_identity_hash = _hash(
            executor_identity_hash, "executor_identity_hash")
        claim_nonce_hash = _hash(claim_nonce_hash, "claim_nonce_hash")
        if plan.content_hash != plan_hash:
            raise ExecutionClaimError("plan_hash_mismatch")
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
            raise ExecutionClaimError("plan_or_target_mismatch")
        for name in ("approval", "proposal", "verification", "target"):
            if not isinstance(body.get(name), dict) or not body[name]:
                raise ExecutionClaimError("invalid_plan")
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
            "executor_identity_hash": executor_identity_hash,
            "claim_nonce_hash": claim_nonce_hash,
        }
        return tx.put("execution_claim", plan_hash, payload)
    except IdempotencyConflict as exc:
        raise ExecutionClaimError("plan_already_claimed") from exc
    except (KeyError, TypeError, ValueError, AttributeError,
            json.JSONDecodeError) as exc:
        if isinstance(exc, ExecutionClaimError):
            raise
        raise ExecutionClaimError("execution_claim_rejected") from exc


def load_execution_claim(tx, identity):
    """Reload and verify immutable tenant-bound claim evidence."""
    try:
        record = tx.get_by_id(identity, kind="execution_claim")
    except (ValueError, TypeError):
        record = None
    if record is None or record["tenant_id"] != tx.tenant_id:
        raise ExecutionClaimError("not_found_or_not_authorized")
    try:
        payload = json.loads(record["payload"])
    except (TypeError, json.JSONDecodeError):
        raise ExecutionClaimError("integrity_failure") from None
    if (payload.get("version") != VERSION
            or payload.get("purpose") != PURPOSE
            or payload.get("tenant_id") != str(tx.tenant_id)
            or payload.get("plan_hash") != record["idempotency_key"]
            or sha256(record["payload"].encode("utf-8")).hexdigest()
            != record["content_hash"]):
        raise ExecutionClaimError("integrity_failure")
    for name in ("plan_hash", "boundary_hash", "observed_target_state_hash",
                 "executor_identity_hash", "claim_nonce_hash"):
        if type(payload.get(name)) is not str or _HASH.fullmatch(
                payload[name]) is None:
            raise ExecutionClaimError("integrity_failure")
    return record
