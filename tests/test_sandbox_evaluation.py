import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

import air.sandbox_evaluation as se
from air.postgres import canonical_json, IdempotencyConflict


class Memory:
    def __init__(self):
        self.tenant_id = uuid4()
        self.records = {}
    def put(self, kind, key, payload):
        encoded = canonical_json(payload)
        old = self.get(kind, key)
        if old:
            if old["payload"] != encoded:
                raise IdempotencyConflict("conflict")
            return old
        record = dict(tenant_id=self.tenant_id, artifact_id=uuid4(), kind=kind,
                      idempotency_key=key, payload=encoded,
                      content_hash=se._digest(payload), created_at=datetime.now(timezone.utc))
        self.records[str(record["artifact_id"])] = record
        return record
    def get(self, kind, key):
        return next((r for r in self.records.values()
                     if r["kind"] == kind and r["idempotency_key"] == key), None)
    def get_by_id(self, identity, *, kind):
        r = self.records.get(str(identity))
        return r if r and r["kind"] == kind else None


@pytest.fixture
def approved(monkeypatch):
    tx = Memory()
    proposal_body = {
        "tenant_id": str(tx.tenant_id),
        "revision": 3,
        "impact": {"artifact_id": str(uuid4()), "artifact_hash": "a" * 64},
        "change_evidence": {"artifact_id": str(uuid4()), "artifact_hash": "b" * 64},
        "description": {"proposed_state": {"mapping": {"field": "new_name"}}},
    }
    proposal = tx.put("repair_proposal", se._digest(proposal_body), proposal_body)
    calls = []
    def authorize(t, proposal_id, **kwargs):
        calls.append((proposal_id, kwargs))
        if kwargs != {"proposal_hash": proposal["content_hash"], "revision": 3,
                      "current_impact_id": proposal_body["impact"]["artifact_id"]}:
            raise ValueError("not_authorized")
        return object()
    monkeypatch.setattr(se, "authorization", authorize)
    monkeypatch.setattr(se, "load_proposal", lambda t, identity: proposal)
    monkeypatch.setattr(se, "reference", lambda r: {
        "artifact_id": str(r["artifact_id"]), "artifact_hash": r["content_hash"]})
    return tx, proposal, proposal_body, calls


def evaluate(approved):
    tx, proposal, body, _ = approved
    return se.evaluate(tx, proposal["artifact_id"],
                       proposal_hash=proposal["content_hash"], revision=3,
                       current_impact_id=body["impact"]["artifact_id"])


def test_evaluation_is_authorized_deterministic_and_immutable(approved):
    tx, proposal, body, calls = approved
    first = evaluate(approved)
    second = evaluate(approved)
    assert first == second
    assert len(calls) == 2
    payload = json.loads(first["payload"])
    assert payload["result"]["status"] == "PASS"
    assert payload["result"]["state_hash"] == se._digest(body["description"]["proposed_state"])
    assert payload["proposal"]["artifact_id"] == str(proposal["artifact_id"])
    assert payload["revision"] == 3
    assert payload["impact"] == body["impact"]
    assert payload["change_evidence"] == body["change_evidence"]


@pytest.mark.parametrize("bad", [
    {"proposal_hash": "0" * 64},
    {"revision": 2},
    {"current_impact_id": "stale-impact"},
])
def test_exact_approval_binding_is_rechecked(approved, bad):
    tx, proposal, body, _ = approved
    args = dict(proposal_hash=proposal["content_hash"], revision=3,
                current_impact_id=body["impact"]["artifact_id"])
    args.update(bad)
    with pytest.raises(ValueError, match="not_authorized"):
        se.evaluate(tx, proposal["artifact_id"], **args)
    assert tx.get("sandbox_evaluation", "anything") is None


@pytest.mark.parametrize("state", [
    {"x": float("nan")},
    {"x": float("inf")},
    {"x": object()},
])
def test_invalid_declarative_state_fails_closed(approved, state):
    tx, proposal, body, _ = approved
    body["description"]["proposed_state"] = state
    with pytest.raises((se.SandboxError, ValueError, TypeError)):
        evaluate(approved)
    assert not any(r["kind"] == "sandbox_evaluation" for r in tx.records.values())


def test_depth_bound_fails_closed(approved):
    tx, proposal, body, _ = approved
    state = {}
    cursor = state
    for _ in range(se.MAX_DEPTH + 2):
        cursor["x"] = {}
        cursor = cursor["x"]
    body["description"]["proposed_state"] = state
    with pytest.raises(se.SandboxError, match="sandbox_bounds_exceeded"):
        evaluate(approved)
    assert not any(r["kind"] == "sandbox_evaluation" for r in tx.records.values())


def test_byte_bound_fails_closed(approved):
    tx, proposal, body, _ = approved
    body["description"]["proposed_state"] = {"x": "z" * (se.MAX_BYTES + 1)}
    with pytest.raises(se.SandboxError, match="sandbox_bounds_exceeded"):
        evaluate(approved)


def test_cross_tenant_and_tampered_evidence_fail_reload(approved):
    tx, _, _, _ = approved
    record = evaluate(approved)
    original_tenant = tx.tenant_id
    tx.tenant_id = uuid4()
    with pytest.raises(se.SandboxError, match="not_found_or_not_authorized"):
        se.load_evaluation(tx, record["artifact_id"])
    tx.tenant_id = original_tenant
    record["payload"] = record["payload"].replace('"PASS"', '"FAIL"')
    with pytest.raises(se.SandboxError, match="invalid_evaluation"):
        se.load_evaluation(tx, record["artifact_id"])


def test_missing_evaluation_is_indistinguishable_from_foreign(approved):
    tx, _, _, _ = approved
    for identity in (uuid4(), "bad", None):
        with pytest.raises(se.SandboxError, match="not_found_or_not_authorized"):
            se.load_evaluation(tx, identity)
