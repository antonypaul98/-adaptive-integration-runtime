from dataclasses import FrozenInstanceError
import json
from uuid import uuid4

import pytest

from air.approval_review import prepare_review, ReviewError
from air import replay_verification as rv, sandbox_evaluation as se
from air.repair_proposal import ProposalError
from test_repair_proposal import context, make, decide, description
from test_replay_verification import run, fixture


def review(tx, proposal, verification, **overrides):
    p, v = json.loads(proposal["payload"]), json.loads(verification["payload"])
    args = dict(proposal_hash=proposal["content_hash"], revision=p["revision"],
                current_impact_id=p["impact"]["artifact_id"],
                verification_id=verification["artifact_id"],
                verification_hash=verification["content_hash"], fixture_hash=v["fixture_hash"])
    args.update(overrides)
    return prepare_review(tx, proposal["artifact_id"], **args)


@pytest.fixture
def evidence(context):
    tx, impact, _ = context
    p = make(context); decide(tx, p)
    s = se.evaluate(tx, p["artifact_id"], proposal_hash=p["content_hash"], revision=1,
                    current_impact_id=impact["artifact_id"])
    return tx, p, s, run(tx, p, s)


def test_deterministic_review_has_evidence_and_no_mutation(evidence):
    tx, p, _, v = evidence
    before = dict(tx.records)
    a = review(tx, p, v)
    assert a == review(tx, p, v)
    assert a.content_hash == rv.digest(json.loads(a.payload))
    assert tx.records == before
    b = json.loads(a.payload)
    assert b["purpose"] == "REVIEW_ONLY_NO_DEPLOYMENT_AUTHORITY"
    assert b["proposal_description"]["proposed_state"] == {"field": "new_name"}
    assert b["fixture"]["cases"][0]["expected"] == "new_name"
    assert b["verification"]["artifact_id"] == str(v["artifact_id"])
    with pytest.raises(FrozenInstanceError):
        a.payload = "changed"


@pytest.mark.parametrize("override", [
    {"proposal_hash": "0" * 64}, {"revision": 2}, {"revision": True},
    {"current_impact_id": uuid4()}, {"verification_id": uuid4()},
    {"verification_hash": "0" * 64}, {"fixture_hash": "0" * 64},
])
def test_exact_bindings_are_required(evidence, override):
    tx, p, _, v = evidence
    with pytest.raises((ReviewError, ProposalError, rv.ReplayError)):
        review(tx, p, v, **override)


@pytest.mark.parametrize("field", ["proposal_hash", "verification_hash", "fixture_hash"])
@pytest.mark.parametrize("value", [None, True, "", "A" * 64, "0" * 63])
def test_malformed_hashes_fail_closed(evidence, field, value):
    tx, p, _, v = evidence
    with pytest.raises(ReviewError, match="invalid_evidence_hash"):
        review(tx, p, v, **{field: value})


def test_failing_replay_cannot_be_reviewed_as_ready(evidence):
    tx, p, s, _ = evidence
    failed = run(tx, p, s, fixture("incorrect"))
    with pytest.raises(ReviewError, match="verification_not_passed"):
        review(tx, p, failed)


def test_another_passing_fixture_cannot_replace_selected_fixture(evidence):
    tx, p, s, original = evidence
    alternate = fixture(); alternate["cases"][0]["case_id"] = "different-test"
    replacement = run(tx, p, s, alternate)
    with pytest.raises(ReviewError, match="verification_binding_mismatch"):
        review(tx, p, replacement, fixture_hash=json.loads(original["payload"])["fixture_hash"])


def test_another_approved_proposals_replay_is_rejected(context, evidence):
    tx, p, _, v = evidence
    desc = description(); desc["rationale"] = "A different proposal with same state"
    other = make(context, desc); decide(tx, other)
    with pytest.raises(ReviewError, match="verification_binding_mismatch"):
        review(tx, other, v)


def test_supersession_invalidates_review_but_not_historical_replay(context, evidence):
    tx, p, _, v = evidence
    review(tx, p, v)
    make(context, supersedes=p["artifact_id"])
    assert rv.load_verification(tx, v["artifact_id"]) == v
    with pytest.raises(ProposalError):
        review(tx, p, v)


def test_tenant_and_tamper_fail_closed(evidence):
    tx, p, _, v = evidence
    original = v["tenant_id"]
    v["tenant_id"] = uuid4()
    with pytest.raises(rv.ReplayError): review(tx, p, v)
    v["tenant_id"] = original
    v["payload"] = v["payload"].replace('"PASS"', '"FAIL"')
    with pytest.raises(rv.ReplayError): review(tx, p, v)


def test_removed_approval_is_not_hidden_by_historical_pass(evidence):
    tx, p, _, v = evidence
    decision = tx.get("repair_decision", str(p["artifact_id"]))
    del tx.records[str(decision["artifact_id"])]
    with pytest.raises(ProposalError): review(tx, p, v)
