"""Bounded deterministic sandbox evaluation for approved repair proposals.

This module evaluates declarative proposed state only. It has no network, filesystem,
subprocess, adapter execution, production-write, or deployment capability.
"""
import json
from hashlib import sha256

from .postgres import canonical_json
from .repair_proposal import ProposalError, authorization, load_proposal, reference

VERSION = "air-sandbox-evaluation-v1"
MAX_NODES = 4096
MAX_DEPTH = 16
MAX_BYTES = 65536


class SandboxError(ValueError):
    pass


def _walk(value, depth=0, count=None):
    if count is None:
        count = [0]
    count[0] += 1
    if count[0] > MAX_NODES or depth > MAX_DEPTH:
        raise SandboxError("sandbox_bounds_exceeded")
    if isinstance(value, dict):
        for key in sorted(value):
            if not isinstance(key, str):
                raise SandboxError("invalid_state")
            _walk(value[key], depth + 1, count)
    elif isinstance(value, list):
        for item in value:
            _walk(item, depth + 1, count)
    elif value is None or isinstance(value, (str, bool, int)):
        return
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise SandboxError("invalid_state")
    else:
        raise SandboxError("invalid_state")


def _digest(value):
    return sha256(canonical_json(value).encode()).hexdigest()


def evaluate(tx, proposal_id, *, proposal_hash, revision, current_impact_id):
    """Persist immutable evidence for an exact currently-approved proposal."""
    authorization(tx, proposal_id, proposal_hash=proposal_hash, revision=revision,
                  current_impact_id=current_impact_id)
    proposal = load_proposal(tx, proposal_id)
    body = json.loads(proposal["payload"])
    state = body["description"]["proposed_state"]
    encoded = canonical_json(state)
    if len(encoded.encode()) > MAX_BYTES:
        raise SandboxError("sandbox_bounds_exceeded")
    _walk(state)
    result = {
        "status": "PASS",
        "state_hash": _digest(state),
        "checks": ["canonical_state", "bounded_structure", "declarative_only"],
    }
    payload = {
        "tenant_id": str(tx.tenant_id),
        "sandbox_version": VERSION,
        "proposal": reference(proposal),
        "revision": revision,
        "impact": body["impact"],
        "change_evidence": body["change_evidence"],
        "result": result,
    }
    return tx.put("sandbox_evaluation", _digest(payload), payload)


def load_evaluation(tx, identity):
    try:
        record = tx.get_by_id(identity, kind="sandbox_evaluation")
    except (ValueError, TypeError):
        record = None
    if record is None or record["tenant_id"] != tx.tenant_id:
        raise SandboxError("not_found_or_not_authorized")
    try:
        payload = json.loads(record["payload"])
        proposal = load_proposal(tx, payload["proposal"]["artifact_id"])
        p = json.loads(proposal["payload"])
    except (KeyError, TypeError, json.JSONDecodeError, ProposalError):
        raise SandboxError("invalid_evaluation") from None
    expected = {
        "tenant_id": str(tx.tenant_id),
        "sandbox_version": VERSION,
        "proposal": reference(proposal),
        "revision": p["revision"],
        "impact": p["impact"],
        "change_evidence": p["change_evidence"],
        "result": payload.get("result"),
    }
    if (canonical_json(expected) != record["payload"]
            or _digest(expected) != record["idempotency_key"]
            or _digest(expected) != record["content_hash"]
            or expected["result"].get("status") != "PASS"):
        raise SandboxError("invalid_evaluation")
    return record
