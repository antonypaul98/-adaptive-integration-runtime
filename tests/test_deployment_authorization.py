"""Read-only authorization boundary adversarial tests."""
import json
from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest
from air.deployment_authorization import ExecutionBoundaryError, prepare_execution_boundary
from test_approval_review import evidence
from test_final_approval import call
from test_repair_proposal import context, make


def check(tx, proposal, verification, approval, **overrides):
    p = json.loads(proposal["payload"])
    v = json.loads(verification["payload"])
    target = json.loads(approval["payload"])["target"]
    args = dict(proposal_hash=proposal["content_hash"], revision=p["revision"],
                current_impact_id=p["impact"]["artifact_id"],
                verification_id=verification["artifact_id"],
                verification_hash=verification["content_hash"],
                fixture_hash=v["fixture_hash"],
                review_hash=json.loads(approval["payload"])["review_hash"],
                environment=target["environment"], integration_id=target["integration_id"],
                mapping_id=target["mapping_id"], scope=target["scope"])
    approval_id = overrides.pop("approval_id", approval["artifact_id"])
    args.update(overrides)
    return prepare_execution_boundary(tx, approval_id, proposal["artifact_id"], **args)


def test_receipt_is_read_only_and_deterministic(evidence):
    tx, proposal, _, verification = evidence
    approval = call(tx, proposal, verification)
    before = dict(tx.records)
    receipt = check(tx, proposal, verification, approval)
    assert receipt == check(tx, proposal, verification, approval)
    assert json.loads(receipt.payload)["purpose"] == "READ_ONLY_PREFLIGHT_NO_DEPLOYMENT_EXECUTION"
    assert tx.records == before
    with pytest.raises(FrozenInstanceError):
        receipt.payload = "changed"


@pytest.mark.parametrize("override", [
    {"environment": "production"}, {"integration_id": "billing"},
    {"mapping_id": "wrong"}, {"scope": {"region": "elsewhere"}},
    {"review_hash": "0"*64}, {"verification_hash": "0"*64},
    {"fixture_hash": "0"*64}, {"current_impact_id": uuid4()},
    {"revision": 0}, {"revision": True}, {"approval_id": uuid4()},
])
def test_mismatched_evidence_or_target_fails_closed(evidence, override):
    tx, proposal, _, verification = evidence
    approval = call(tx, proposal, verification)
    with pytest.raises(ExecutionBoundaryError):
        check(tx, proposal, verification, approval, **override)


def test_supersession_fails_closed(context, evidence):
    tx, proposal, _, verification = evidence
    approval = call(tx, proposal, verification)
    check(tx, proposal, verification, approval)
    make(context, supersedes=proposal["artifact_id"])
    with pytest.raises(ExecutionBoundaryError):
        check(tx, proposal, verification, approval)
