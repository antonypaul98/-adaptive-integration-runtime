"""PostgreSQL enforcement for tenant-scoped redacted AIR-23 investigations."""

from copy import deepcopy
import json
from uuid import uuid4

import psycopg
import pytest

from air import failure_investigation as fi
from air.postgres import canonical_json
from test_repair_evidence import reviewer
from test_replay_verification import fixture, run
from test_replay_verification_postgres import approved, sandbox
from test_workflow_evidence import saved


pytestmark = pytest.mark.postgres


@pytest.fixture
def failed_verification(database, repos, approved, sandbox):
    with repos[0].transaction(database["tenants"][0]) as tx:
        return run(tx, approved, sandbox, fixture("synthetic-wrong-value"))


def test_persist_reload_idempotent_redacted_and_audited(database, repos, failed_verification):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        first = fi.persist_investigation(tx, failed_verification["artifact_id"])
        second = fi.persist_investigation(tx, failed_verification["artifact_id"])
        assert first == second
    with repos[0].transaction(tenant) as tx:
        assert fi.load_investigation(tx, first["artifact_id"]) == first
        payload = json.loads(first["payload"])
        report = json.loads(payload["report_payload"])
        assert report["source"]["status"] == "FAIL"
        assert report["authority"] == "DIAGNOSTIC_ONLY_NO_REPAIR_OR_EXECUTION_AUTHORITY"
        assert report["coverage"]["root_cause_coverage"] == "NOT_ESTABLISHED"
        assert "synthetic-wrong-value" not in first["payload"]
        assert "path" not in report
        assert len([event for event in tx.audit()
                    if event["artifact_id"] == first["artifact_id"]]) == 1


def test_passing_replay_persists_explicitly_without_findings(
        database, repos, approved, sandbox):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        verification = run(tx, approved, sandbox)
        record = fi.persist_investigation(tx, verification["artifact_id"])
        report = json.loads(json.loads(record["payload"])["report_payload"])
        assert report["source"]["status"] == "PASS"
        assert report["findings"] == []
        assert report["review_required"] is False


def _mutate(payload, mutation):
    value = deepcopy(payload)
    report = json.loads(value["report_payload"])
    if mutation == "extra":
        value["grant_repair"] = True
    elif mutation == "tenant":
        value["tenant_id"] = str(uuid4())
    elif mutation == "record_version":
        value["investigation_record_version"] = "v2"
    elif mutation == "verification":
        value["verification"]["artifact_id"] = str(uuid4())
    elif mutation == "verification_hash":
        value["verification"]["artifact_hash"] = "0" * 64
    elif mutation == "report_hash":
        value["report_hash"] = "0" * 64
    elif mutation == "finding_id":
        report["findings"][0]["finding_id"] = "0" * 64
    elif mutation == "actual_hash":
        report["findings"][0]["evidence"]["actual_hash"] = "0" * 64
    elif mutation == "coverage":
        report["coverage"]["failing_cases"] = 0
    elif mutation == "authority":
        report["authority"] = "REPAIR_ALLOWED"
    elif mutation == "finding_extra":
        report["findings"][0]["private_value"] = "synthetic"
    if mutation in {"finding_id", "actual_hash", "coverage", "authority", "finding_extra"}:
        value["report_payload"] = canonical_json(report)
        value["report_hash"] = fi._digest(report)
    return value


@pytest.mark.parametrize("mutation", [
    "extra", "tenant", "record_version", "verification", "verification_hash",
    "report_hash", "finding_id", "actual_hash", "coverage", "authority",
    "finding_extra", "key",
])
def test_database_rejects_forged_investigation(
        database, repos, failed_verification, mutation):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        original = fi.persist_investigation(tx, failed_verification["artifact_id"])
    payload = _mutate(json.loads(original["payload"]), mutation)
    key = uuid4().hex if mutation == "key" else fi._digest(payload)
    with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.InsufficientPrivilege)):
        with repos[0].transaction(tenant) as tx:
            tx.put("failure_investigation", key, payload)


def test_cross_tenant_read_and_forged_link_fail_closed(
        database, repos, failed_verification):
    with repos[0].transaction(database["tenants"][0]) as tx:
        record = fi.persist_investigation(tx, failed_verification["artifact_id"])
    with repos[1].transaction(database["tenants"][1]) as tx:
        with pytest.raises(fi.InvestigationError, match="not_found_or_not_authorized"):
            fi.load_investigation(tx, record["artifact_id"])
        payload = json.loads(record["payload"])
        payload["tenant_id"] = str(tx.tenant_id)
        with pytest.raises(psycopg.errors.CheckViolation):
            tx.put("failure_investigation", fi._digest(payload), payload)


@pytest.mark.parametrize("verb", [
    "UPDATE air.artifacts SET payload=payload", "DELETE FROM air.artifacts",
])
def test_investigation_is_append_only(database, repos, failed_verification, verb):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        record = fi.persist_investigation(tx, failed_verification["artifact_id"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(tenant) as tx:
            tx._connection.execute(verb + " WHERE artifact_id=%s", (record["artifact_id"],))


def test_rollback_leaves_no_investigation(database, repos, failed_verification):
    tenant = database["tenants"][0]
    with pytest.raises(RuntimeError):
        with repos[0].transaction(tenant) as tx:
            record = fi.persist_investigation(tx, failed_verification["artifact_id"])
            raise RuntimeError("rollback")
    with repos[0].transaction(tenant) as tx:
        assert tx.get_by_id(record["artifact_id"], kind="failure_investigation") is None
        assert not [event for event in tx.audit()
                    if event["artifact_id"] == record["artifact_id"]]
