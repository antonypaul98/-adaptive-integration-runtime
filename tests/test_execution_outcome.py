"""Append-only single-use outcome evidence tests."""
from hashlib import sha256
import json
from uuid import UUID, uuid4

import pytest

from air.execution_claim import claim_execution
from air.execution_outcome import (
    ExecutionOutcomeError,
    load_execution_outcome,
    record_execution_outcome,
)
from air.execution_plan import ExecutionPlan
from air.postgres import IdempotencyConflict, canonical_json


TENANT = UUID("00000000-0000-0000-0000-000000000001")


class Tx:
    def __init__(self, tenant_id=TENANT):
        self.tenant_id = tenant_id
        self.records = {}

    def put(self, kind, key, payload):
        serialized = canonical_json(payload)
        old = self.records.get((kind, key))
        if old is not None:
            if old["payload"] != serialized:
                raise IdempotencyConflict("conflict")
            return old
        record = {
            "artifact_id": uuid4(), "tenant_id": self.tenant_id,
            "kind": kind, "idempotency_key": key, "payload": serialized,
            "content_hash": sha256(serialized.encode()).hexdigest(),
        }
        self.records[(kind, key)] = record
        return record

    def get_by_id(self, identity, *, kind):
        return next((record for (record_kind, _), record in self.records.items()
                     if record_kind == kind
                     and record["artifact_id"] == UUID(str(identity))), None)


def plan(tenant=TENANT):
    return ExecutionPlan(canonical_json({
        "version": "air-execution-plan-v1",
        "purpose": "READ_ONLY_EXECUTION_PLAN_NO_DEPLOYMENT_EXECUTION",
        "operation": "activate_approved_mapping_revision",
        "tenant_id": str(tenant),
        "boundary_hash": "1" * 64,
        "target_state_hash": "2" * 64,
        "approval": {"artifact_id": "approval", "artifact_hash": "3" * 64},
        "proposal": {"artifact_id": "proposal", "artifact_hash": "4" * 64},
        "revision": 7,
        "verification": {"artifact_id": "verification", "artifact_hash": "5" * 64},
        "review_hash": "6" * 64,
        "target": {"environment": "staging", "integration_id": "orders",
                   "mapping_id": "orders-v7", "scope": {"region": "us-east-1"}},
        "executor_requirements": {
            "append_only_outcome_evidence": True,
            "revalidate_boundary": True,
            "revalidate_target_state_hash": True,
            "single_use": True,
        },
    }))


def claim(tx, source):
    return claim_execution(
        tx, source, plan_hash=source.content_hash,
        observed_target_state_hash="2" * 64,
        executor_identity_hash="8" * 64,
        claim_nonce_hash="9" * 64)


def record(tx, source, *, saved_claim=None, **overrides):
    if saved_claim is None:
        saved_claim = claim(tx, source)
    args = {
        "claim_id": saved_claim["artifact_id"],
        "plan_hash": source.content_hash,
        "observed_target_state_hash": "2" * 64,
        "status": "succeeded",
        "outcome_hash": "7" * 64,
        "reason_code": "verified_completion",
    }
    args.update(overrides)
    return record_execution_outcome(tx, source, **args)


def test_outcome_is_append_only_single_use_and_idempotent():
    tx = Tx()
    source = plan()
    saved = record(tx, source)
    assert record(tx, source) == saved
    assert len(tx.records) == 2
    body = json.loads(saved["payload"])
    assert body["purpose"] == "APPEND_ONLY_OUTCOME_EVIDENCE_NO_DEPLOYMENT_EXECUTION"
    assert body["plan_hash"] == source.content_hash
    assert body["claim"] == {
        "artifact_id": str(next(record for (kind, _), record in tx.records.items()
                           if kind == "execution_claim")["artifact_id"]),
        "artifact_hash": next(record for (kind, _), record in tx.records.items()
                              if kind == "execution_claim")["content_hash"],
        "executor_identity_hash": "8" * 64,
        "claim_nonce_hash": "9" * 64,
    }
    assert load_execution_outcome(tx, saved["artifact_id"]) == saved
    with pytest.raises(ExecutionOutcomeError, match="plan_already_consumed"):
        record(tx, source, status="failed", outcome_hash="8" * 64,
               reason_code="executor_failure")


@pytest.mark.parametrize("overrides", [
    {"plan_hash": "0" * 64},
    {"observed_target_state_hash": "0" * 64},
    {"status": "pending"},
    {"status": True},
    {"outcome_hash": "bad"},
    {"reason_code": "contains private detail"},
])
def test_mismatched_or_unbounded_outcome_fails_closed(overrides):
    tx = Tx()
    source = plan()
    saved_claim = claim(tx, source)
    with pytest.raises(ExecutionOutcomeError):
        record(tx, source, saved_claim=saved_claim, **overrides)
    assert not any(kind == "execution_outcome" for kind, _ in tx.records)


def test_outcome_requires_exact_persisted_claim():
    tx = Tx()
    source = plan()
    with pytest.raises(ExecutionOutcomeError, match="claim_not_found_or_invalid"):
        record_execution_outcome(
            tx, source, claim_id=uuid4(), plan_hash=source.content_hash,
            observed_target_state_hash="2" * 64, status="succeeded",
            outcome_hash="7" * 64, reason_code="verified_completion")
    assert tx.records == {}


def test_cross_tenant_plan_fails_closed():
    tx = Tx(UUID("00000000-0000-0000-0000-000000000002"))
    with pytest.raises(ExecutionOutcomeError):
        record(tx, plan(), saved_claim={"artifact_id": uuid4()})
    assert tx.records == {}


def test_load_rejects_tampered_evidence():
    tx = Tx()
    saved = record(tx, plan())
    saved["payload"] = saved["payload"].replace("succeeded", "aborted")
    with pytest.raises(ExecutionOutcomeError, match="integrity_failure"):
        load_execution_outcome(tx, saved["artifact_id"])
