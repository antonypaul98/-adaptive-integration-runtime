from copy import deepcopy
import json

import pytest

from air import replay_verification as rv, sandbox_evaluation as se
from air.repair_proposal import ProposalError
from test_repair_proposal import context, make, decide


def fixture(expected="new_name"):
    return {"version": rv.VERSION, "cases": [
        {"case_id": "field", "input": {"path": ["field"]}, "expected": expected}]}


def run(tx, proposal, sandbox, value=None, **overrides):
    body = json.loads(proposal["payload"])
    args = dict(proposal_hash=proposal["content_hash"], revision=body["revision"],
                current_impact_id=body["impact"]["artifact_id"],
                sandbox_id=sandbox["artifact_id"], sandbox_hash=sandbox["content_hash"],
                fixture=fixture() if value is None else value)
    args.update(overrides)
    return rv.replay(tx, proposal["artifact_id"], **args)


def test_deterministic_normalization_and_strict_json_comparison():
    f = fixture()
    f["cases"].append({"case_id": "a", "input": {"path": ["number"]}, "expected": 1.0})
    state = {"field": "new_name", "number": 1}
    result = rv.compare(state, f)
    assert result == rv.compare(dict(reversed(list(state.items()))), {**f, "cases": list(reversed(f["cases"]))})
    assert result["status"] == "FAIL"
    assert [c["case_id"] for c in result["cases"]] == ["a", "field"]
    assert result["cases"][1]["matches"] is True


@pytest.mark.parametrize("value", [None, True, 7, 1.5, "é", [1, 2], {"z": 1, "a": 2}])
def test_supported_json_values(value):
    assert rv.compare({"field": value}, fixture(value))["status"] == "PASS"


@pytest.mark.parametrize("mutation", ["version", "extra", "empty", "many", "duplicate", "case_extra", "path_type", "input_extra", "missing_path", "nan", "depth", "nodes", "bytes", "cycle"])
def test_invalid_or_unbounded_fixtures_fail_closed(mutation):
    f = fixture()
    if mutation == "version": f["version"] = "v2"
    elif mutation == "extra": f["execute"] = "ignored?"
    elif mutation == "empty": f["cases"] = []
    elif mutation == "many": f["cases"] *= 33
    elif mutation == "duplicate": f["cases"] *= 2
    elif mutation == "case_extra": f["cases"][0]["code"] = "print('no')"
    elif mutation == "path_type": f["cases"][0]["input"]["path"] = [0]
    elif mutation == "input_extra": f["cases"][0]["input"]["operation"] = "execute"
    elif mutation == "missing_path": f["cases"][0]["input"]["path"] = ["missing"]
    elif mutation == "nan": f["cases"][0]["expected"] = float("nan")
    elif mutation == "depth":
        v = {}
        for _ in range(17): v = {"nested": v}
        f["cases"][0]["expected"] = v
    elif mutation == "nodes": f["cases"][0]["expected"] = list(range(4096))
    elif mutation == "bytes": f["cases"][0]["expected"] = "x" * 65536
    elif mutation == "cycle": f["cases"][0]["expected"] = f
    with pytest.raises(rv.ReplayError): rv.compare({"field": "new_name"}, f)


def test_evidence_is_idempotent_reload_verified_and_requires_fresh_authorization(context):
    tx, impact, _ = context
    p = make(context)
    decide(tx, p)
    s = se.evaluate(tx, p["artifact_id"], proposal_hash=p["content_hash"], revision=1,
                    current_impact_id=impact["artifact_id"])
    record = run(tx, p, s)
    assert run(tx, p, s) == record
    assert rv.load_verification(tx, record["artifact_id"]) == record
    assert json.loads(record["payload"])["result"]["status"] == "PASS"
    assert json.loads(run(tx, p, s, fixture("wrong"))["payload"])["result"]["status"] == "FAIL"
    with pytest.raises(rv.ReplayError): run(tx, p, s, sandbox_hash="0" * 64)
    with pytest.raises(ProposalError): run(tx, p, s, proposal_hash="0" * 64)
    make(context, supersedes=p["artifact_id"])
    with pytest.raises(ProposalError): run(tx, p, s)
    # Historical read is permitted but must not authorize another replay.
    assert rv.load_verification(tx, record["artifact_id"]) == record


def test_reload_rejects_tampered_result_even_with_rehashed_record(context):
    tx, impact, _ = context
    p = make(context); decide(tx, p)
    s = se.evaluate(tx, p["artifact_id"], proposal_hash=p["content_hash"], revision=1,
                    current_impact_id=impact["artifact_id"])
    record = run(tx, p, s)
    payload = json.loads(record["payload"])
    payload["result"]["cases"][0]["actual_hash"] = "0" * 64
    forged = tx.put("replay_verification", rv.digest(payload), payload)
    with pytest.raises(rv.ReplayError): rv.load_verification(tx, forged["artifact_id"])
