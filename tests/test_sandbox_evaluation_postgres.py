import json
from copy import deepcopy
from uuid import uuid4

import psycopg
import pytest

import air.sandbox_evaluation as se
import air.repair_proposal as rp
from test_repair_evidence import create, reviewer
from test_repair_proposal import decide
from test_workflow_evidence import saved

pytestmark = pytest.mark.postgres


@pytest.fixture
def approved(database, repos, reviewer, saved):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        proposal = create(tx, saved)
    with reviewer.transaction(tenant) as tx:
        decide(tx, proposal)
    return proposal


def evaluate(tx, proposal, saved):
    body = json.loads(proposal["payload"])
    return se.evaluate(
        tx,
        proposal["artifact_id"],
        proposal_hash=proposal["content_hash"],
        revision=body["revision"],
        current_impact_id=saved["impact"]["artifact_id"],
    )


def test_postgres_evaluation_persists_and_reloads(database, repos, approved, saved):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        first = evaluate(tx, approved, saved)
        second = evaluate(tx, approved, saved)
        assert first == second
    with repos[0].transaction(tenant) as tx:
        assert se.load_evaluation(tx, first["artifact_id"]) == first
        assert len([a for a in tx.audit() if a["artifact_id"] == first["artifact_id"]]) == 1


@pytest.mark.parametrize("mutation", [
    "proposal", "proposal_hash", "revision", "impact", "change", "tenant",
    "status", "state_hash", "checks", "extra", "key",
])
def test_database_rejects_forged_sandbox_evidence(database, repos, approved, saved, mutation):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        valid = evaluate(tx, approved, saved)
        payload = deepcopy(json.loads(valid["payload"]))

    if mutation == "proposal":
        payload["proposal"]["artifact_id"] = str(uuid4())
    elif mutation == "proposal_hash":
        payload["proposal"]["artifact_hash"] = "0" * 64
    elif mutation == "revision":
        payload["revision"] += 1
    elif mutation == "impact":
        payload["impact"]["artifact_id"] = str(uuid4())
    elif mutation == "change":
        payload["change_evidence"]["artifact_id"] = str(uuid4())
    elif mutation == "tenant":
        payload["tenant_id"] = str(database["tenants"][1])
    elif mutation == "status":
        payload["result"]["status"] = "FAIL"
    elif mutation == "state_hash":
        payload["result"]["state_hash"] = "0" * 63
    elif mutation == "checks":
        payload["result"]["checks"] = ["declarative_only"]
    elif mutation == "extra":
        payload["unexpected"] = True

    with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.InsufficientPrivilege)):
        with repos[0].transaction(tenant) as tx:
            tx.put(
                "sandbox_evaluation",
                uuid4().hex if mutation == "key" else se._digest(payload),
                payload,
            )


def test_cross_tenant_evaluation_is_hidden_and_cannot_be_inserted(database, repos, approved, saved):
    with repos[0].transaction(database["tenants"][0]) as tx:
        record = evaluate(tx, approved, saved)
        payload = json.loads(record["payload"])

    with repos[1].transaction(database["tenants"][1]) as tx:
        with pytest.raises(se.SandboxError, match="not_found_or_not_authorized"):
            se.load_evaluation(tx, record["artifact_id"])
        assert tx._connection.execute(
            "SELECT * FROM air.artifacts WHERE artifact_id=%s", (record["artifact_id"],)
        ).fetchall() == []
        payload["tenant_id"] = str(database["tenants"][1])
        with pytest.raises(psycopg.errors.CheckViolation):
            tx.put("sandbox_evaluation", se._digest(payload), payload)


@pytest.mark.parametrize("verb", [
    "UPDATE air.artifacts SET payload=payload",
    "DELETE FROM air.artifacts",
])
def test_sandbox_evidence_is_append_only(database, repos, approved, saved, verb):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        record = evaluate(tx, approved, saved)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(tenant) as tx:
            tx._connection.execute(verb + " WHERE artifact_id=%s", (record["artifact_id"],))


def test_stale_superseded_proposal_cannot_gain_sandbox_evidence(
    database, repos, reviewer, approved, saved
):
    tenant = database["tenants"][0]
    with reviewer.transaction(tenant) as tx:
        create(tx, saved, supersedes=approved["artifact_id"])
    with repos[0].transaction(tenant) as tx:
        with pytest.raises(rp.ProposalError):
            evaluate(tx, approved, saved)
        assert tx._connection.execute(
            """SELECT count(*) AS n FROM air.artifacts
               WHERE kind='sandbox_evaluation'
                 AND payload::jsonb#>>'{proposal,artifact_id}'=%s""",
            (str(approved["artifact_id"]),),
        ).fetchone()["n"] == 0


def raw_payload(tenant, proposal):
    body = json.loads(proposal["payload"])
    return {
        "tenant_id": str(tenant), "sandbox_version": se.VERSION,
        "proposal": rp.reference(proposal), "revision": body["revision"],
        "impact": body["impact"], "change_evidence": body["change_evidence"],
        "result": {"status": "PASS",
                   "state_hash": se._digest(body["description"]["proposed_state"]),
                   "checks": ["canonical_state", "bounded_structure", "declarative_only"]},
    }


@pytest.mark.parametrize("decision", [None, "REJECTED"])
def test_raw_insert_requires_exact_approved_proposal(database, repos, reviewer, saved, decision):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        proposal = create(tx, saved)
    if decision:
        with reviewer.transaction(tenant) as tx:
            decide(tx, proposal, decision)
    payload = raw_payload(tenant, proposal)
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(tenant) as tx:
            tx.put("sandbox_evaluation", se._digest(payload), payload)


def test_raw_insert_rejects_wrong_well_formed_state_hash(database, repos, approved):
    tenant = database["tenants"][0]
    payload = raw_payload(tenant, approved)
    payload["result"]["state_hash"] = "0" * 64
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(tenant) as tx:
            tx.put("sandbox_evaluation", se._digest(payload), payload)


def test_raw_insert_rejects_superseded_proposal(database, repos, approved, saved):
    tenant = database["tenants"][0]
    payload = raw_payload(tenant, approved)
    with repos[0].transaction(tenant) as tx:
        create(tx, saved, supersedes=approved["artifact_id"])
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(tenant) as tx:
            tx.put("sandbox_evaluation", se._digest(payload), payload)


@pytest.mark.parametrize("bound", ["depth", "nodes"])
def test_raw_insert_enforces_structural_bounds(database, repos, reviewer, saved, bound):
    from test_repair_proposal import description
    tenant = database["tenants"][0]
    desc = description()
    state = {"x": list(range(se.MAX_NODES))}
    if bound == "depth":
        state = {"x": 1}
        for _ in range(se.MAX_DEPTH + 1):
            state = {"x": state}
    desc["proposed_state"] = state
    impact = json.loads(saved["impact"]["payload"])
    with repos[0].transaction(tenant) as tx:
        proposal = rp.create_proposal(tx, saved["impact"]["artifact_id"],
                                     impact["analysis"]["impacts"][0]["impact_id"], desc)
    with reviewer.transaction(tenant) as tx:
        decide(tx, proposal)
    payload = raw_payload(tenant, proposal)
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(tenant) as tx:
            tx.put("sandbox_evaluation", se._digest(payload), payload)
