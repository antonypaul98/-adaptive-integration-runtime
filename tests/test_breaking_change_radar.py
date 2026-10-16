from copy import deepcopy
from dataclasses import replace
import json

import pytest

from air.breaking_change_radar import (
    ChangeObservation,
    RadarError,
    compare_risk_windows,
    rank_breaking_risks,
)
from air.change_intelligence import compare_openapi


def spec():
    return {
        "openapi": "3.1.0",
        "info": {"title": "Demo", "version": "1"},
        "paths": {"/items": {"get": {"responses": {
            "200": {"description": "OK", "content": {"application/json": {
                "schema": {"type": "object", "properties": {
                    "id": {"type": "integer"}}}}}}}}}},
    }


def evidence(kind="breaking"):
    old, new = spec(), spec()
    if kind == "breaking":
        new["paths"].clear()
    elif kind == "nonbreaking":
        new["paths"]["/extra"] = deepcopy(new["paths"]["/items"])
    else:
        new["paths"]["/items"]["get"]["responses"]["400"] = {"description": "Bad"}
    return compare_openapi(old, new)


def observation(at, kind="breaking"):
    return ChangeObservation(at, evidence(kind))


def test_deterministic_ranking_provenance_and_uncertainty_are_explicit():
    observations = [
        observation("2026-01-01T00:00:00Z"),
        observation("2026-02-01T00:00:00Z", "review"),
        observation("2026-03-01T00:00:00Z"),
    ]
    first = rank_breaking_risks(observations)
    second = rank_breaking_risks(reversed(observations))
    assert first.payload_json == second.payload_json
    assert first.content_hash == second.content_hash
    payload = first.to_dict()
    assert payload["source"]["first_observed_at"] == "2026-01-01T00:00:00Z"
    assert payload["source"]["last_observed_at"] == "2026-03-01T00:00:00Z"
    assert payload["signals"][0]["classification"] == "BREAKING"
    assert payload["signals"][0]["evidence"]["observation_count"] == 2
    assert payload["signals"][0]["score_kind"] == "HEURISTIC_POINTS_NOT_PROBABILITY"
    assert payload["coverage"]["false_positive_rate"].startswith("NOT_MEASURABLE")
    assert payload["review_required"] is True
    assert payload["authority"].startswith("DIAGNOSTIC_ONLY")


def test_nonbreaking_history_is_visible_but_does_not_create_risk_signal():
    result = rank_breaking_risks([
        observation("2026-01-01T00:00:00Z", "nonbreaking"),
        observation("2026-02-01T00:00:00Z", "nonbreaking"),
    ]).to_dict()
    assert result["signals"] == []
    assert result["coverage"]["ignored_non_breaking_events"] == 2
    assert result["review_required"] is False


@pytest.mark.parametrize("items,code", [
    ([], "observation_count_out_of_bounds"),
    ([observation("2026-01-01T00:00:00Z")], "observation_count_out_of_bounds"),
    ([observation("2026-01-01T00:00:00Z")] * 65, "observation_count_out_of_bounds"),
    ([object(), object()], "invalid_observation"),
])
def test_input_bounds_and_shapes_fail_closed(items, code):
    with pytest.raises(RadarError, match=f"^{code}$"):
        rank_breaking_risks(items)


def test_duplicate_invalid_time_and_unsupported_evidence_fail_closed():
    item = observation("2026-01-01T00:00:00Z")
    with pytest.raises(RadarError, match="^duplicate_observation$"):
        rank_breaking_risks([item, item])
    with pytest.raises(RadarError, match="^invalid_observed_at$"):
        rank_breaking_risks([item, observation("2026-02-30T00:00:00Z")])
    forged = replace(evidence(), version="future-version")
    with pytest.raises(RadarError, match="^unsupported_change_evidence$"):
        rank_breaking_risks([item, ChangeObservation("2026-02-01T00:00:00Z", forged)])

    leaked = replace(evidence(), changes=(
        replace(evidence().changes[0], change_type="SECRET_CUSTOM_SIGNAL"),))
    with pytest.raises(RadarError, match="^invalid_change_evidence$"):
        rank_breaking_risks([item, ChangeObservation("2026-02-01T00:00:00Z", leaked)])


def test_output_contains_no_raw_contract_values_or_change_locations():
    result = rank_breaking_risks([
        observation("2026-01-01T00:00:00Z"),
        observation("2026-02-01T00:00:00Z"),
    ])
    assert "/items" not in result.payload_json
    assert "old_value" not in result.payload_json
    assert "new_value" not in result.payload_json
    assert json.dumps(spec(), sort_keys=True) not in result.payload_json


def test_window_trends_are_deterministic_exactly_bound_and_uncertain():
    baseline = [
        observation("2026-01-01T00:00:00Z"),
        observation("2026-01-02T00:00:00Z", "nonbreaking"),
    ]
    candidate = [
        observation("2026-02-01T00:00:00Z"),
        observation("2026-02-02T00:00:00Z"),
    ]
    first = compare_risk_windows(baseline, candidate)
    second = compare_risk_windows(reversed(baseline), reversed(candidate))
    assert first.payload_json == second.payload_json
    payload = first.to_dict()
    assert payload["source"]["baseline_radar_hash"] == rank_breaking_risks(
        baseline).content_hash
    assert payload["source"]["candidate_radar_hash"] == rank_breaking_risks(
        candidate).content_hash
    assert payload["trends"][0]["direction"] == "RISING_HEURISTIC_POINTS"
    assert payload["trends"][0]["score_delta"] > 0
    assert payload["trends"][0]["score_kind"].endswith("NOT_PROBABILITY")
    assert payload["coverage"]["false_positive_rate"].startswith("NOT_MEASURABLE")
    assert "do not predict" in payload["uncertainty"][0]
    assert payload["authority"].startswith("DIAGNOSTIC_ONLY")


def test_window_trends_show_new_and_unobserved_signals_without_safety_claims():
    baseline = [
        observation("2026-01-01T00:00:00Z"),
        observation("2026-01-02T00:00:00Z"),
    ]
    candidate = [
        observation("2026-02-01T00:00:00Z", "review"),
        observation("2026-02-02T00:00:00Z", "review"),
    ]
    payload = compare_risk_windows(baseline, candidate).to_dict()
    assert {item["direction"] for item in payload["trends"]} == {
        "NEWLY_OBSERVED", "NOT_OBSERVED_IN_CANDIDATE_WINDOW"}
    assert any("not evidence" in item for item in payload["uncertainty"])


def test_window_trends_reject_overlap_and_do_not_leak_contract_values():
    baseline = [
        observation("2026-01-01T00:00:00Z"),
        observation("2026-02-01T00:00:00Z"),
    ]
    overlapping = [
        observation("2026-02-01T00:00:00Z", "review"),
        observation("2026-03-01T00:00:00Z", "review"),
    ]
    with pytest.raises(RadarError, match="^risk_windows_not_strictly_ordered$"):
        compare_risk_windows(baseline, overlapping)

    candidate = [
        observation("2026-03-01T00:00:00Z"),
        observation("2026-04-01T00:00:00Z"),
    ]
    report = compare_risk_windows(baseline, candidate)
    assert "/items" not in report.payload_json
    assert "old_value" not in report.payload_json
    assert "new_value" not in report.payload_json
