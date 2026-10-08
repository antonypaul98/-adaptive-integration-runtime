"""Real PostgreSQL adversarial coverage for persisted target-bound human approval."""
from copy import deepcopy
from hashlib import sha256
import json
from uuid import uuid4

import psycopg
import pytest

from air.final_approval import FinalApprovalError, load_final_approval
from air.postgres import canonical_json
from test_final_approval import call
from test_replay_verification import run
from test_replay_verification_postgres import sandbox
from test_sandbox_evaluation_postgres import approved
from test_repair_evidence import reviewer, create
from test_workflow_evidence import saved

pytestmark = pytest.mark.postgres


@pytest.fixture
def approval_inputs(database, repos, approved, sandbox):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        verification = run(tx, approved, sandbox)
    return tenant, approved, verification


def test_authenticated_persistence_reload_idempotency_and_audit(database, reviewer, approval_inputs):
    tenant, proposal, verification = approval_inputs
    with reviewer.transaction(tenant) as tx:
        record = call(tx, proposal, verification)
        assert call(tx, proposal, verification) == record
        assert load_final_approval(tx, record["artifact_id"]) == record
        payload = json.loads(record["payload"])
        assert payload["reviewer"].startswith("human:reviewer_")
        assert payload["confirmed"] is True
        assert sha256(payload["review_payload"].encode()).hexdigest() == payload["review_hash"]
        assert len([e for e in tx.audit() if e["artifact_id"] == record["artifact_id"]]) == 1


@pytest.mark.parametrize("mutation", [
    "reviewer", "confirmed", "review_hash", "review_payload", "review_fixture",
    "proposal", "proposal_hash", "decision", "decision_hash", "verification",
    "verification_hash", "sandbox", "sandbox_hash", "fixture_hash", "revision",
    "impact", "change", "target_integration", "target_mapping", "target_scope",
    "target_environment", "tenant", "extra", "key"
])
def test_database_rejects_raw_insert_forgery(database, reviewer, approval_inputs, mutation):
    tenant, proposal, verification = approval_inputs
    with reviewer.transaction(tenant) as tx:
        valid = call(tx, proposal, verification)
    p = deepcopy(json.loads(valid["payload"]))
    if mutation == "reviewer": p["reviewer"] = "human:impostor"
    elif mutation == "confirmed": p["confirmed"] = False
    elif mutation == "review_hash": p["review_hash"] = "0" * 64
    elif mutation == "review_payload": p["review_payload"] = "{}"
    elif mutation == "review_fixture":
        material = json.loads(p["review_payload"])
        material["fixture"]["cases"][0]["case_id"] = "tampered"
        p["review_payload"] = canonical_json(material)
        p["review_hash"] = sha256(p["review_payload"].encode()).hexdigest()
    elif mutation in ("proposal", "decision", "verification", "sandbox"):
        field = "prior_proposal_decision" if mutation == "decision" else mutation
        p[field]["artifact_id"] = str(uuid4())
    elif mutation in ("proposal_hash", "decision_hash", "verification_hash", "sandbox_hash"):
        field = mutation.removesuffix("_hash")
        field = "prior_proposal_decision" if field == "decision" else field
        p[field]["artifact_hash"] = "0" * 64
    elif mutation == "fixture_hash": p["fixture_hash"] = "0" * 64
    elif mutation == "revision": p["revision"] += 1
    elif mutation == "impact": p["impact"]["artifact_id"] = str(uuid4())
    elif mutation == "change": p["change_evidence"]["artifact_id"] = str(uuid4())
    elif mutation == "target_integration": p["target"]["integration_id"] = "billing"
    elif mutation == "target_mapping": p["target"]["mapping_id"] = "wrong"
    elif mutation == "target_scope": p["target"]["scope"] = {"region": []}
    elif mutation == "target_environment": p["target"]["environment"] = ""
    elif mutation == "tenant": p["tenant_id"] = str(database["tenants"][1])
    elif mutation == "extra": p["deployment_allowed"] = True
    with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.InsufficientPrivilege)):
        with reviewer.transaction(tenant) as tx:
            tx.put("final_approval", "0"*64 if mutation == "key" else
                   sha256(canonical_json(p).encode()).hexdigest(), p)


def test_non_reviewer_cannot_insert_or_read_other_tenant(database, repos, reviewer, approval_inputs):
    tenant, proposal, verification = approval_inputs
    with reviewer.transaction(tenant) as tx:
        valid = call(tx, proposal, verification)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(tenant) as tx:
            tx.put("final_approval", sha256(valid["payload"].encode()).hexdigest(),
                   json.loads(valid["payload"]))
    with repos[1].transaction(database["tenants"][1]) as tx:
        with pytest.raises(FinalApprovalError):
            load_final_approval(tx, valid["artifact_id"])
        assert tx._connection.execute(
            "SELECT * FROM air.artifacts WHERE artifact_id=%s",
            (valid["artifact_id"],)).fetchall() == []


def test_supersession_rejects_raw_final_approval(database, reviewer, approval_inputs, saved):
    tenant, proposal, verification = approval_inputs
    with reviewer.transaction(tenant) as tx:
        valid = call(tx, proposal, verification)
    with reviewer.transaction(tenant) as tx:
        create(tx, saved, supersedes=proposal["artifact_id"])
    with pytest.raises(psycopg.errors.CheckViolation):
        with reviewer.transaction(tenant) as tx:
            p = json.loads(valid["payload"])
            tx.put("final_approval", sha256(valid["payload"].encode()).hexdigest(), p)


@pytest.mark.parametrize("verb", [
    "UPDATE air.artifacts SET payload=payload",
    "DELETE FROM air.artifacts"
])
def test_final_approval_is_immutable(database, reviewer, approval_inputs, verb):
    tenant, proposal, verification = approval_inputs
    with reviewer.transaction(tenant) as tx:
        valid = call(tx, proposal, verification)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with reviewer.transaction(tenant) as tx:
            tx._connection.execute(verb+" WHERE artifact_id=%s", (valid["artifact_id"],))
