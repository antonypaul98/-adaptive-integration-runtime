from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest

from air import replay_verification as rv, repair_proposal as rp
from test_sandbox_evaluation_postgres import approved, evaluate
from test_repair_evidence import create, reviewer
from test_workflow_evidence import saved
from test_replay_verification import fixture, run
from test_repair_proposal import description, decide

pytestmark = pytest.mark.postgres


@pytest.fixture
def sandbox(database, repos, approved, saved):
    with repos[0].transaction(database["tenants"][0]) as tx:
        return evaluate(tx, approved, saved)


@pytest.mark.parametrize("expected,status", [("new_name", "PASS"), ("wrong", "FAIL")])
def test_committed_reload_and_idempotent_audit(database, repos, approved, sandbox, expected, status):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        a = run(tx, approved, sandbox, fixture(expected))
        assert a == run(tx, approved, sandbox, fixture(expected))
    with repos[0].transaction(tenant) as tx:
        assert rv.load_verification(tx, a["artifact_id"]) == a
        assert json.loads(a["payload"])["result"]["status"] == status
        assert len([r for r in tx.audit() if r["artifact_id"] == a["artifact_id"]]) == 1


@pytest.mark.parametrize("mutation", ["proposal", "proposal_hash", "sandbox", "sandbox_hash", "revision", "impact", "change", "tenant", "status", "actual_hash", "expected_hash", "matches", "fixture_hash", "fixture_extra", "version", "path", "duplicate", "extra", "key"])
def test_direct_insert_rejects_forgery(database, repos, approved, sandbox, mutation):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        record = run(tx, approved, sandbox)
    p = deepcopy(json.loads(record["payload"]))
    if mutation in {"proposal", "sandbox", "impact"}: p[mutation]["artifact_id"] = str(uuid4())
    elif mutation in {"proposal_hash", "sandbox_hash"}: p[mutation.split('_')[0]]["artifact_hash"] = "0"*64
    elif mutation == "revision": p["revision"] = 2
    elif mutation == "change": p["change_evidence"]["artifact_id"] = str(uuid4())
    elif mutation == "tenant": p["tenant_id"] = str(database["tenants"][1])
    elif mutation == "status": p["result"]["status"] = "FAIL"
    elif mutation in {"actual_hash", "expected_hash"}: p["result"]["cases"][0][mutation] = "0"*64
    elif mutation == "matches": p["result"]["cases"][0]["matches"] = False
    elif mutation == "fixture_hash": p["fixture_hash"] = "0"*64
    elif mutation == "fixture_extra": p["fixture"]["execute"] = "no"
    elif mutation == "version": p["replay_version"] = "v2"
    elif mutation == "path": p["fixture"]["cases"][0]["input"]["path"] = ["missing"]
    elif mutation == "duplicate": p["fixture"]["cases"] *= 2
    elif mutation == "extra": p["grant_deployment"] = True
    if mutation in {"fixture_extra", "path", "duplicate"}: p["fixture_hash"] = rv.digest(p["fixture"])
    with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.InsufficientPrivilege)):
        with repos[0].transaction(tenant) as tx:
            tx.put("replay_verification", uuid4().hex if mutation == "key" else rv.digest(p), p)


def test_tenant_isolation_and_cross_tenant_links(database, repos, approved, sandbox):
    with repos[0].transaction(database["tenants"][0]) as tx: record = run(tx, approved, sandbox)
    with repos[1].transaction(database["tenants"][1]) as tx:
        with pytest.raises(rv.ReplayError): rv.load_verification(tx, record["artifact_id"])
        assert tx._connection.execute("SELECT * FROM air.artifacts WHERE artifact_id=%s", (record["artifact_id"],)).fetchall() == []
        p = json.loads(record["payload"]); p["tenant_id"] = str(tx.tenant_id)
        with pytest.raises(psycopg.errors.CheckViolation): tx.put("replay_verification", rv.digest(p), p)


@pytest.mark.parametrize("verb", ["UPDATE air.artifacts SET payload=payload", "DELETE FROM air.artifacts"])
def test_immutable_replay(database, repos, approved, sandbox, verb):
    with repos[0].transaction(database["tenants"][0]) as tx: record = run(tx, approved, sandbox)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database["tenants"][0]) as tx:
            tx._connection.execute(verb + " WHERE artifact_id=%s", (record["artifact_id"],))


def test_supersession_rejects_api_and_direct_insert(database, repos, approved, sandbox, saved):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx: record = run(tx, approved, sandbox)
    with repos[0].transaction(tenant) as tx: create(tx, saved, supersedes=approved["artifact_id"])
    with repos[0].transaction(tenant) as tx:
        with pytest.raises(rp.ProposalError): run(tx, approved, sandbox)
    p = json.loads(record["payload"])
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(tenant) as tx: tx.put("replay_verification", rv.digest(p), p)


def test_concurrent_idempotent_replay(database, repos, approved, sandbox):
    def task(_):
        with repos[0].transaction(database["tenants"][0]) as tx: return run(tx, approved, sandbox)
    with ThreadPoolExecutor(max_workers=2) as pool: records = list(pool.map(task, range(2)))
    assert records[0] == records[1]


@pytest.mark.parametrize("bound", ["empty", "cases", "depth", "nodes", "bytes", "unordered", "path_type"])
def test_database_enforces_fixture_bounds_independently(database, repos, approved, sandbox, bound):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx: record = run(tx, approved, sandbox)
    p = json.loads(record["payload"])
    f = p["fixture"]
    if bound == "empty": f["cases"] = []
    elif bound == "cases": f["cases"] *= 33
    elif bound == "depth":
        v = {}
        for _ in range(17): v = {"x": v}
        f["cases"][0]["expected"] = v
    elif bound == "nodes": f["cases"][0]["expected"] = list(range(4096))
    elif bound == "bytes": f["cases"][0]["expected"] = "x" * 65536
    elif bound == "unordered":
        f["cases"].append({"case_id": "a", "input": {"path": ["field"]}, "expected": "new_name"})
    elif bound == "path_type": f["cases"][0]["input"]["path"] = [0]
    # Bypass Python replay validation deliberately; exercise real DB enforcement.
    p["fixture_hash"] = sha256(rp.canonical_json(f).encode()).hexdigest()
    errors = {"empty": "replay case bound", "cases": "replay case bound",
              "depth": "replay structural bound", "nodes": "replay structural bound",
              "bytes": "invalid replay fixture", "unordered": "invalid or unordered replay case",
              "path_type": "unsupported or missing replay path"}
    with pytest.raises(psycopg.errors.CheckViolation, match=errors[bound]):
        with repos[0].transaction(tenant) as tx: tx.put("replay_verification", rp.digest(p), p)


def test_rollback_leaves_no_replay_evidence(database, repos, approved, sandbox):
    tenant = database["tenants"][0]
    with pytest.raises(RuntimeError):
        with repos[0].transaction(tenant) as tx:
            record = run(tx, approved, sandbox)
            raise RuntimeError("rollback")
    with repos[0].transaction(tenant) as tx:
        assert tx.get_by_id(record["artifact_id"], kind="replay_verification") is None
        assert not [a for a in tx.audit() if a["artifact_id"] == record["artifact_id"]]


@pytest.mark.parametrize("actual,expected,status", [
    (None, None, "PASS"), (True, True, "PASS"), (1, 1.0, "FAIL"),
    (1.5, 1.5, "PASS"), ("é", "é", "PASS"),
    ([1, 2], [1, 2], "PASS"), ({"z": 1, "a": 2}, {"a": 2, "z": 1}, "PASS"),
])
def test_database_and_python_compare_the_same_canonical_json(database, repos, reviewer, saved, actual, expected, status):
    tenant = database["tenants"][0]
    desc = description(); desc["proposed_state"] = {"field": actual}
    item = json.loads(saved["impact"]["payload"])["analysis"]["impacts"][0]["impact_id"]
    with repos[0].transaction(tenant) as tx:
        proposal = rp.create_proposal(tx, saved["impact"]["artifact_id"], item, desc)
    with reviewer.transaction(tenant) as tx: decide(tx, proposal)
    with repos[0].transaction(tenant) as tx:
        sandbox = evaluate(tx, proposal, saved)
        record = run(tx, proposal, sandbox, fixture(expected))
    with repos[0].transaction(tenant) as tx:
        assert rv.load_verification(tx, record["artifact_id"]) == record
        assert json.loads(record["payload"])["result"]["status"] == status
