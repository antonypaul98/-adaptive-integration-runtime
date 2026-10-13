from copy import deepcopy
import json

import pytest

from air import failure_investigation as fi
from air import replay_verification as replay


def fixture(expected="expected"):
    return {"version": replay.VERSION, "cases": [
        {"case_id": "field", "input": {"path": ["field"]}, "expected": expected},
    ]}


def test_mismatch_has_deterministic_explainable_evidence_without_values():
    secret_actual = "SYNTHETIC_PRIVATE_ACTUAL_2301"
    secret_expected = "SYNTHETIC_PRIVATE_EXPECTED_2301"
    report = fi.investigate_replay({"field": secret_actual}, fixture(secret_expected))
    payload = report.to_dict()

    assert payload["source"]["status"] == "FAIL"
    assert payload["coverage"] == {
        "analyzed_cases": 1,
        "failing_cases": 1,
        "scope": "recorded_projection_cases_only",
        "root_cause_coverage": "NOT_ESTABLISHED",
    }
    assert payload["review_required"] is True
    assert payload["authority"] == "DIAGNOSTIC_ONLY_NO_REPAIR_OR_EXECUTION_AUTHORITY"
    assert payload["findings"][0]["code"] == "RECORDED_VALUE_MISMATCH"
    assert payload["findings"][0]["confidence"] == "CONFIRMED"
    assert len(payload["findings"][0]["finding_id"]) == 64
    assert secret_actual not in report.payload_json
    assert secret_expected not in report.payload_json
    assert "field" in report.payload_json  # bounded case ID, not the recorded value


def test_report_is_canonical_and_bound_to_fixture_and_observed_hashes():
    data = fixture()
    data["cases"].append(
        {"case_id": "alpha", "input": {"path": ["other"]}, "expected": {"a": 2}}
    )
    state = {"field": "actual", "other": {"a": 1}}
    first = fi.investigate_replay(state, data)
    reordered = deepcopy(data)
    reordered["cases"].reverse()
    second = fi.investigate_replay(dict(reversed(list(state.items()))), reordered)

    assert first == second
    assert first.content_hash == second.content_hash
    assert [item["case_id"] for item in first.to_dict()["findings"]] == ["alpha", "field"]
    changed = fixture("different")
    assert (fi.investigate_replay({"field": "actual"}, changed).to_dict()["source"]["fixture_hash"]
            != first.to_dict()["source"]["fixture_hash"])


def test_pass_is_explicit_but_does_not_claim_general_coverage():
    payload = fi.investigate_replay({"field": "expected"}, fixture()).to_dict()
    assert payload["source"]["status"] == "PASS"
    assert payload["findings"] == []
    assert payload["review_required"] is False
    assert payload["coverage"]["root_cause_coverage"] == "NOT_ESTABLISHED"
    assert payload["uncertainty"]


def test_strict_json_type_difference_is_explained_as_a_failure():
    payload = fi.investigate_replay({"field": 1}, fixture(1.0)).to_dict()
    finding = payload["findings"][0]
    assert finding["evidence"]["actual_hash"] != finding["evidence"]["expected_hash"]


@pytest.mark.parametrize("mutation", ["extra", "empty", "duplicate", "execute", "oversized"])
def test_invalid_or_unbounded_inputs_fail_closed_through_replay_boundary(mutation):
    data = fixture()
    if mutation == "extra":
        data["extra"] = True
    elif mutation == "empty":
        data["cases"] = []
    elif mutation == "duplicate":
        data["cases"] *= 2
    elif mutation == "execute":
        data["cases"][0]["input"]["operation"] = "execute"
    elif mutation == "oversized":
        data["cases"][0]["expected"] = "x" * replay.MAX_BYTES
    with pytest.raises(replay.ReplayError):
        fi.investigate_replay({"field": "actual"}, data)


def test_report_shape_contains_no_state_path_or_expected_payload():
    actual_value = "SYNTHETIC_PRIVATE_ACTUAL_VALUE_2302"
    expected_value = "SYNTHETIC_PRIVATE_EXPECTED_VALUE_2302"
    report = fi.investigate_replay(
        {"private_path": {"nested": actual_value}},
        {"version": replay.VERSION, "cases": [{
            "case_id": "synthetic-case",
            "input": {"path": ["private_path", "nested"]},
            "expected": {"private": expected_value},
        }]},
    )
    text = json.dumps(report.to_dict())
    assert "private_path" not in text
    assert "nested" not in text
    assert '"private"' not in text
    assert actual_value not in text
    assert expected_value not in text
