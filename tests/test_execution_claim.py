"""Append-only pre-execution claim tests."""
from hashlib import sha256
import json
from uuid import UUID, uuid4

import pytest

from air.execution_claim import (
    ExecutionClaimError,
    claim_execution,
    load_execution_claim,
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


def claim(tx, source, **overrides):
    args = {
        "plan_hash": source.content_hash,
        "observed_target_state_hash": "2" * 64,
        "executor_identity_hash": "7" * 64,
        "claim_nonce_hash": "8" * 64,
    }
    args.update(overrides)
    return claim_execution(tx, source, **args)


def test_claim_is_single_use_append_only_and_idempotent():
    tx = Tx()
    source = plan()
    saved = claim(tx, source)
    assert claim(tx, source) == saved
    assert len(tx.records) == 1
    body = json.loads(saved["payload"])
    assert body["purpose"] == "APPEND_ONLY_SINGLE_USE_CLAIM_NO_DEPLOYMENT_EXECUTION"
    assert body["plan_hash"] == source.content_hash
    assert load_execution_claim(tx, saved["artifact_id"]) == saved
    with pytest.raises(ExecutionClaimError, match="plan_already_claimed"):
        claim(tx, source, executor_identity_hash="9" * 64)
    with pytest.raises(ExecutionClaimError, match="plan_already_claimed"):
        claim(tx, source, claim_nonce_hash="a" * 64)


@pytest.mark.parametrize("overrides", [
    {"plan_hash": "0" * 64},
    {"observed_target_state_hash": "0" * 64},
    {"executor_identity_hash": "bad"},
    {"claim_nonce_hash": ""},
    {"claim_nonce_hash": True},
])
def test_mismatched_or_unbounded_claim_fails_closed(overrides):
    tx = Tx()
    with pytest.raises(ExecutionClaimError):
        claim(tx, plan(), **overrides)
    assert tx.records == {}


def test_cross_tenant_plan_and_read_fail_closed():
    owner = Tx()
    saved = claim(owner, plan())
    other = Tx(UUID("00000000-0000-0000-0000-000000000002"))
    with pytest.raises(ExecutionClaimError):
        claim(other, plan())
    other.records = owner.records
    with pytest.raises(ExecutionClaimError, match="not_found_or_not_authorized"):
        load_execution_claim(other, saved["artifact_id"])


def test_load_rejects_tampered_or_malformed_evidence():
    tx = Tx()
    saved = claim(tx, plan())
    saved["payload"] = saved["payload"].replace("7" * 64, "not-a-hash")
    with pytest.raises(ExecutionClaimError, match="integrity_failure"):
        load_execution_claim(tx, saved["artifact_id"])
    with pytest.raises(ExecutionClaimError, match="not_found_or_not_authorized"):
        load_execution_claim(tx, "not-a-uuid")
