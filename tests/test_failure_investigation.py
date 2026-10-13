from copy import deepcopy
import json

import pytest

from air.change_intelligence import compare_openapi
from air.dependency_impact import Dependency, ImpactReport, analyze_changes
from air import failure_investigation as fi
from air import replay_verification as replay
from air.postgres import canonical_json


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


def lifecycle_evidence():
    old = {"openapi": "3.1.0", "info": {"title": "Synthetic", "version": "1"},
           "paths": {"/items": {"get": {"responses": {"200": {"content": {
               "application/json": {"schema": {"type": "object", "properties": {
                   "id": {"type": "string"}}}}}}}}}}}
    new = deepcopy(old)
    new["paths"]["/items"]["get"]["responses"]["200"]["content"][
        "application/json"]["schema"]["properties"]["id"]["type"] = "integer"
    changes = compare_openapi(old, new)
    report = analyze_changes(changes, [Dependency(
        integration_id="synthetic-adapter",
        mapping_id="synthetic-id",
        operation="GET /items",
        location=("/paths/~1items/get/responses/200/content/application~1json/schema/"
                  "properties/id"),
    )])
    return changes, report


def test_declared_candidate_is_exactly_bound_redacted_and_not_causal_proof():
    private_actual = "SYNTHETIC_PRIVATE_ACTUAL_2303"
    private_expected = "SYNTHETIC_PRIVATE_EXPECTED_2303"
    investigation = fi.investigate_replay(
        {"private": private_actual},
        {"version": replay.VERSION, "cases": [{
            "case_id": "recorded-case", "input": {"path": ["private"]},
            "expected": private_expected,
        }]},
    )
    changes, impact_report = lifecycle_evidence()
    impact_id = impact_report.to_dict()["impacts"][0]["impact_id"]
    result = fi.correlate_candidates(
        investigation, changes, impact_report,
        [fi.CandidateLink("recorded-case", impact_id)],
    )
    payload = result.to_dict()

    assert payload["source"] == {
        "investigation_hash": investigation.content_hash,
        "fixture_hash": investigation.to_dict()["source"]["fixture_hash"],
        "change_set_hash": changes.content_hash,
        "impact_report_hash": impact_report.content_hash,
        "impact_version": impact_report.to_dict()["impact_version"],
    }
    candidate, = payload["candidates"]
    assert candidate["confidence"] == "SUPPORTED_CORRELATION_NOT_CAUSAL_PROOF"
    assert candidate["basis"] == "DECLARED_TEST_DEPENDENCY"
    assert candidate["impact_match"] == "LOCATION_OVERLAP"
    assert payload["coverage"]["root_cause_coverage"] == "NOT_ESTABLISHED"
    assert payload["authority"] == "DIAGNOSTIC_ONLY_NO_REPAIR_OR_EXECUTION_AUTHORITY"
    assert private_actual not in result.payload_json
    assert private_expected not in result.payload_json
    assert "/items" not in result.payload_json
    assert "synthetic-adapter" not in result.payload_json


def test_candidate_order_and_duplicate_links_are_deterministic():
    investigation = fi.investigate_replay(
        {"a": 0, "b": 0},
        {"version": replay.VERSION, "cases": [
            {"case_id": "b", "input": {"path": ["b"]}, "expected": 1},
            {"case_id": "a", "input": {"path": ["a"]}, "expected": 1},
        ]},
    )
    changes, report = lifecycle_evidence()
    impact_id = report.to_dict()["impacts"][0]["impact_id"]
    links = [fi.CandidateLink("b", impact_id), fi.CandidateLink("a", impact_id)]
    first = fi.correlate_candidates(investigation, changes, report, links)
    second = fi.correlate_candidates(investigation, changes, report,
                                     [links[1], links[0], links[1]])
    assert first == second
    assert [candidate["case_id"] for candidate in first.to_dict()["candidates"]] == ["a", "b"]


def test_unmatched_failures_remain_explicit_uncertainty():
    investigation = fi.investigate_replay({"field": "actual"}, fixture())
    changes, report = lifecycle_evidence()
    payload = fi.correlate_candidates(investigation, changes, report, []).to_dict()
    assert payload["candidates"] == []
    assert payload["coverage"]["unmatched_case_ids"] == ["field"]
    assert payload["review_required"] is True
    assert payload["uncertainty"]


@pytest.mark.parametrize("mutation", ["wrong_change_set", "tampered_impact", "unknown_impact",
                                       "passing_case", "unsupported_basis", "invalid_link"])
def test_candidate_correlation_fails_closed_on_unbound_evidence(mutation):
    investigation = fi.investigate_replay({"field": "actual"}, fixture())
    changes, report = lifecycle_evidence()
    impact_id = report.to_dict()["impacts"][0]["impact_id"]
    link = fi.CandidateLink("field", impact_id)
    if mutation == "wrong_change_set":
        other, _ = lifecycle_evidence()
        # A semantically different empty comparison has a different exact hash.
        contract = {"openapi": "3.1.0", "info": {"title": "Other", "version": "1"},
                    "paths": {}}
        other = compare_openapi(contract, contract)
        with pytest.raises(fi.InvestigationError, match="unbound_impact_report"):
            fi.correlate_candidates(investigation, other, report, [link])
    elif mutation == "tampered_impact":
        payload = report.to_dict()
        payload["impacts"][0]["classification"] = "REVIEW_REQUIRED"
        tampered = ImpactReport(canonical_json(payload))
        with pytest.raises(fi.InvestigationError, match="invalid_impact_identity"):
            fi.correlate_candidates(investigation, changes, tampered, [link])
    elif mutation == "unknown_impact":
        with pytest.raises(fi.InvestigationError, match="impact_not_found"):
            fi.correlate_candidates(investigation, changes, report,
                                    [fi.CandidateLink("field", "0" * 64)])
    elif mutation == "passing_case":
        with pytest.raises(fi.InvestigationError, match="case_not_failing"):
            fi.correlate_candidates(investigation, changes, report,
                                    [fi.CandidateLink("other", impact_id)])
    elif mutation == "unsupported_basis":
        with pytest.raises(fi.InvestigationError, match="unsupported_correlation_basis"):
            fi.CandidateLink("field", impact_id, "MODEL_GUESS")
    else:
        with pytest.raises(fi.InvestigationError, match="invalid_candidate_link"):
            fi.correlate_candidates(investigation, changes, report, [object()])


def test_candidate_link_bound_is_fail_closed(monkeypatch):
    investigation = fi.investigate_replay({"field": "actual"}, fixture())
    changes, report = lifecycle_evidence()
    impact_id = report.to_dict()["impacts"][0]["impact_id"]
    monkeypatch.setattr(fi, "MAX_CANDIDATE_LINKS", 1)
    with pytest.raises(fi.InvestigationError, match="candidate_link_limit"):
        fi.correlate_candidates(investigation, changes, report,
                                [fi.CandidateLink("field", impact_id)] * 2)
