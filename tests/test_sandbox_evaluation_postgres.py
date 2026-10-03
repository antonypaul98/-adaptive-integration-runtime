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
