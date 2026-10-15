"""PostgreSQL enforcement for tenant-scoped redacted AIR-23 investigations."""

from copy import deepcopy
import json
from uuid import uuid4

import psycopg
import pytest

from air import failure_investigation as fi
from air.dependency_impact import analyze_and_persist, register_dependencies
from air.postgres import canonical_json
from test_repair_evidence import reviewer
from test_replay_verification import fixture, run
from test_replay_verification_postgres import approved, sandbox
from test_workflow_evidence import graph, saved, setup
from test_workflow_impact import dependencies


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


@pytest.fixture
def persisted_correlation(database, repos, failed_verification, saved):
    tenant = database["tenants"][0]
    impact_payload = json.loads(saved["impact"]["payload"])["analysis"]
    impact_id = impact_payload["impacts"][0]["impact_id"]
    with repos[0].transaction(tenant) as tx:
        investigation = fi.persist_investigation(tx, failed_verification["artifact_id"])
        correlation = fi.persist_candidate_correlation(
            tx,
            investigation["artifact_id"],
            saved["impact"]["artifact_id"],
            [fi.CandidateLink("field", impact_id)],
        )
    return {"investigation": investigation, "correlation": correlation,
            "impact": saved["impact"], "impact_id": impact_id}


def test_persisted_correlation_is_idempotent_redacted_reloadable_and_audited(
        database, repos, persisted_correlation):
    tenant = database["tenants"][0]
    saved = persisted_correlation
    with repos[0].transaction(tenant) as tx:
        second = fi.persist_candidate_correlation(
            tx, saved["investigation"]["artifact_id"], saved["impact"]["artifact_id"],
            [fi.CandidateLink("field", saved["impact_id"])],
        )
        assert second == saved["correlation"]
        assert fi.load_candidate_correlation(tx, second["artifact_id"]) == second
        payload = json.loads(second["payload"])
        correlation = json.loads(payload["correlation_payload"])
        assert payload["investigation"]["artifact_hash"] == saved["investigation"]["content_hash"]
        assert payload["impact"]["artifact_hash"] == saved["impact"]["content_hash"]
        assert correlation["coverage"]["root_cause_coverage"] == "NOT_ESTABLISHED"
        assert correlation["authority"] == "DIAGNOSTIC_ONLY_NO_REPAIR_OR_EXECUTION_AUTHORITY"
        assert "node0" not in second["payload"]
        assert "/node0" not in second["payload"]
        assert len([event for event in tx.audit()
                    if event["artifact_id"] == second["artifact_id"]]) == 1


def _mutate_correlation(payload, mutation):
    value = deepcopy(payload)
    correlation = json.loads(value["correlation_payload"])
    if mutation == "extra":
        value["grant_repair"] = True
    elif mutation == "tenant":
        value["tenant_id"] = str(uuid4())
    elif mutation == "record_version":
        value["correlation_record_version"] = "v2"
    elif mutation == "investigation":
        value["investigation"]["artifact_id"] = str(uuid4())
    elif mutation == "impact_hash":
        value["impact"]["artifact_hash"] = "0" * 64
    elif mutation == "declared_link":
        value["declared_links"][0]["basis"] = "MODEL_GUESS"
    elif mutation == "correlation_hash":
        value["correlation_hash"] = "0" * 64
    elif mutation == "candidate_id":
        correlation["candidates"][0]["candidate_id"] = "0" * 64
    elif mutation == "candidate_evidence":
        correlation["candidates"][0]["evidence"]["change_id"] = "0" * 64
    elif mutation == "coverage":
        correlation["coverage"]["linked_failing_cases"] = 0
    elif mutation == "authority":
        correlation["authority"] = "REPAIR_ALLOWED"
    if mutation in {"candidate_id", "candidate_evidence", "coverage", "authority"}:
        value["correlation_payload"] = canonical_json(correlation)
        value["correlation_hash"] = fi._digest(correlation)
    return value


@pytest.mark.parametrize("mutation", [
    "extra", "tenant", "record_version", "investigation", "impact_hash",
    "declared_link", "correlation_hash", "candidate_id", "candidate_evidence",
    "coverage", "authority", "key",
])
def test_database_rejects_forged_candidate_correlation(
        database, repos, persisted_correlation, mutation):
    tenant = database["tenants"][0]
    payload = _mutate_correlation(
        json.loads(persisted_correlation["correlation"]["payload"]), mutation)
    key = uuid4().hex if mutation == "key" else fi._digest(payload)
    with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.InsufficientPrivilege)):
        with repos[0].transaction(tenant) as tx:
            tx.put("failure_candidate_correlation", key, payload)


def test_candidate_correlation_cross_tenant_and_append_only(
        database, repos, persisted_correlation):
    record = persisted_correlation["correlation"]
    with repos[1].transaction(database["tenants"][1]) as tx:
        with pytest.raises(fi.InvestigationError, match="not_found_or_not_authorized"):
            fi.load_candidate_correlation(tx, record["artifact_id"])
        payload = json.loads(record["payload"])
        payload["tenant_id"] = str(tx.tenant_id)
        with pytest.raises(psycopg.errors.CheckViolation):
            tx.put("failure_candidate_correlation", fi._digest(payload), payload)
    for verb in ("UPDATE air.artifacts SET payload=payload", "DELETE FROM air.artifacts"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with repos[0].transaction(database["tenants"][0]) as tx:
                tx._connection.execute(
                    verb + " WHERE artifact_id=%s", (record["artifact_id"],))


def test_candidate_correlation_rollback_is_atomic(
        database, repos, failed_verification, saved):
    tenant = database["tenants"][0]
    impact_id = json.loads(saved["impact"]["payload"])["analysis"]["impacts"][0]["impact_id"]
    with pytest.raises(RuntimeError):
        with repos[0].transaction(tenant) as tx:
            investigation = fi.persist_investigation(tx, failed_verification["artifact_id"])
            record = fi.persist_candidate_correlation(
                tx, investigation["artifact_id"], saved["impact"]["artifact_id"],
                [fi.CandidateLink("field", impact_id)],
            )
            raise RuntimeError("rollback")
    with repos[0].transaction(tenant) as tx:
        assert tx.get_by_id(record["artifact_id"], kind="failure_candidate_correlation") is None
        assert not [event for event in tx.audit() if event["artifact_id"] == record["artifact_id"]]


def _equivalent_but_distinct_impact(tx):
    previous, changes = setup(tx)
    deps = dependencies()
    registry = register_dependencies(
        tx, previous["artifact_id"], deps, workflow_edges=graph(deps))
    return analyze_and_persist(tx, changes["artifact_id"], registry["artifact_id"])


def test_candidate_requires_exact_replay_bound_impact_not_equivalent_analysis(
        database, repos, failed_verification, saved):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        alternate = _equivalent_but_distinct_impact(tx)
        assert alternate["artifact_id"] != saved["impact"]["artifact_id"]
        assert (json.loads(alternate["payload"])["impact_hash"]
                == json.loads(saved["impact"]["payload"])["impact_hash"])
        investigation = fi.persist_investigation(tx, failed_verification["artifact_id"])
        impact_id = json.loads(alternate["payload"])["analysis"]["impacts"][0]["impact_id"]
        with pytest.raises(fi.InvestigationError, match="lifecycle_binding_mismatch"):
            fi.persist_candidate_correlation(
                tx, investigation["artifact_id"], alternate["artifact_id"],
                [fi.CandidateLink("field", impact_id)])


def test_database_rejects_equivalent_but_wrong_lifecycle_impact(
        database, repos, persisted_correlation):
    tenant = database["tenants"][0]
    original = persisted_correlation["correlation"]
    with repos[0].transaction(tenant) as tx:
        alternate = _equivalent_but_distinct_impact(tx)
        assert (json.loads(alternate["payload"])["impact_hash"]
                == json.loads(persisted_correlation["impact"]["payload"])["impact_hash"])
        payload = json.loads(original["payload"])
        payload["impact"] = {
            "artifact_id": str(alternate["artifact_id"]),
            "artifact_hash": alternate["content_hash"],
        }
        with pytest.raises(psycopg.errors.CheckViolation,
                           match="unbound failure candidate lifecycle"):
            tx.put("failure_candidate_correlation", fi._digest(payload), payload)
