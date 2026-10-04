import json
from uuid import uuid4

import pytest

from air.approval_review import ReviewError
from air.repair_proposal import ProposalError
from air.replay_verification import ReplayError
from test_approval_review import review
from test_replay_verification import run, fixture
from test_replay_verification_postgres import sandbox
from test_sandbox_evaluation_postgres import approved
from test_repair_evidence import create, reviewer
from test_workflow_evidence import saved

pytestmark = pytest.mark.postgres


def test_committed_review_is_repeatable_and_adds_no_artifacts(database, repos, approved, sandbox):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        v = run(tx, approved, sandbox)
    with repos[0].transaction(tenant) as tx:
        audit = tx.audit()
        a = review(tx, approved, v)
        assert tx.audit() == audit
    with repos[0].transaction(tenant) as tx:
        assert review(tx, approved, v) == a
        assert tx.audit() == audit


@pytest.mark.parametrize("override", [
    {"proposal_hash": "0" * 64}, {"revision": 2},
    {"current_impact_id": uuid4()}, {"verification_id": uuid4()},
    {"verification_hash": "0" * 64}, {"fixture_hash": "0" * 64},
])
def test_database_evidence_exact_binding(database, repos, approved, sandbox, override):
    with repos[0].transaction(database["tenants"][0]) as tx:
        v = run(tx, approved, sandbox)
        with pytest.raises((ReviewError, ProposalError, ReplayError)):
            review(tx, approved, v, **override)


def test_cross_tenant_cannot_review(database, repos, approved, sandbox):
    with repos[0].transaction(database["tenants"][0]) as tx:
        v = run(tx, approved, sandbox)
    with repos[1].transaction(database["tenants"][1]) as tx:
        with pytest.raises(ProposalError): review(tx, approved, v)


def test_superseded_proposal_cannot_reuse_passing_review(database, repos, approved, sandbox, saved):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        v = run(tx, approved, sandbox)
        review(tx, approved, v)
    with repos[0].transaction(tenant) as tx:
        create(tx, saved, supersedes=approved["artifact_id"])
    with repos[0].transaction(tenant) as tx:
        with pytest.raises(ProposalError): review(tx, approved, v)


def test_failed_replay_cannot_become_review_ready(database, repos, approved, sandbox):
    with repos[0].transaction(database["tenants"][0]) as tx:
        v = run(tx, approved, sandbox, fixture("wrong"))
        with pytest.raises(ReviewError, match="verification_not_passed"):
            review(tx, approved, v)


def test_passing_fixture_substitution_rejected(database, repos, approved, sandbox):
    with repos[0].transaction(database["tenants"][0]) as tx:
        original = run(tx, approved, sandbox)
        alt = fixture(); alt["cases"][0]["case_id"] = "alternate"
        replacement = run(tx, approved, sandbox, alt)
        with pytest.raises(ReviewError, match="verification_binding_mismatch"):
            review(tx, approved, replacement, fixture_hash=json.loads(original["payload"])["fixture_hash"])
