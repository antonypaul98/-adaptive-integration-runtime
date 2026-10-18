from copy import deepcopy
from dataclasses import replace
import json

import pytest

from air.breaking_change_radar import (
    ChangeObservation,
    RadarError,
    RiskRadar,
    RiskOutcomeLabel,
    calibrate_risk_outcomes,
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


def outcome(radar, at, value="IMPACT_CONFIRMED", signal_id=None):
    return RiskOutcomeLabel(
        observed_at=at,
        radar_hash=radar.content_hash,
        signal_id=signal_id or radar.to_dict()["signals"][0]["signal_id"],
        outcome=value,
    )


def test_outcome_calibration_is_deterministic_bound_and_descriptive_only():
    radar = rank_breaking_risks([
        observation("2026-01-01T00:00:00Z"),
        observation("2026-01-02T00:00:00Z"),
    ])
    labels = [
        outcome(radar, "2026-02-01T00:00:00Z", "NO_IMPACT_OBSERVED"),
        outcome(radar, "2026-02-02T00:00:00Z", "IMPACT_CONFIRMED"),
        outcome(radar, "2026-02-03T00:00:00Z", "NO_IMPACT_OBSERVED"),
        outcome(radar, "2026-02-04T00:00:00Z", "IMPACT_CONFIRMED"),
        outcome(radar, "2026-02-05T00:00:00Z", "NO_IMPACT_OBSERVED"),
    ]
    first = calibrate_risk_outcomes(radar, labels)
    second = calibrate_risk_outcomes(radar, reversed(labels))
    assert first.payload_json == second.payload_json
    payload = first.to_dict()
    assert payload["calibration_version"] == (
        "air-breaking-change-outcome-calibration-v2")
    assert payload["source"]["radar_hash"] == radar.content_hash
    assert payload["coverage"]["resolved_label_count"] == 5
    assert payload["observed_no_impact_rate"]["basis_points"] == 6000
    assert payload["observed_no_impact_rate"]["kind"].endswith("NOT_PROBABILITY")
    signal = payload["signals"][0]
    assert signal["resolved_label_count"] == 5
    assert signal["observed_no_impact_rate"]["basis_points"] == 6000
    assert signal["observed_no_impact_rate"]["kind"].endswith("NOT_PROBABILITY")
    assert any("not independently verified" in item for item in payload["uncertainty"])
    assert payload["authority"].startswith("DIAGNOSTIC_ONLY")


def test_outcome_calibration_exposes_insufficient_samples_and_coverage():
    radar = rank_breaking_risks([
        observation("2026-01-01T00:00:00Z"),
        observation("2026-01-02T00:00:00Z", "review"),
    ])
    label = outcome(radar, "2026-02-01T00:00:00Z", "INCONCLUSIVE")
    payload = calibrate_risk_outcomes(radar, [label]).to_dict()
    assert payload["coverage"]["radar_signal_count"] == 2
    assert payload["coverage"]["labeled_signal_count"] == 1
    assert payload["coverage"]["unlabeled_signal_count"] == 1
    assert payload["observed_no_impact_rate"]["status"] == (
        "INSUFFICIENT_RESOLVED_LABELS")
    assert payload["observed_no_impact_rate"]["basis_points"] is None
    assert payload["signals"][0]["resolved_label_count"] == 0
    assert payload["signals"][0]["observed_no_impact_rate"]["status"] == (
        "INSUFFICIENT_RESOLVED_LABELS")


def test_per_signal_rates_are_independently_gated_and_keep_coverage_visible():
    radar = rank_breaking_risks([
        observation("2026-01-01T00:00:00Z"),
        observation("2026-01-02T00:00:00Z", "review"),
    ])
    signal_ids = [item["signal_id"] for item in radar.to_dict()["signals"]]
    labels = [
        outcome(
            radar,
            f"2026-02-0{index + 1}T00:00:00Z",
            "NO_IMPACT_OBSERVED" if index < 3 else "IMPACT_CONFIRMED",
            signal_ids[0],
        )
        for index in range(5)
    ]
    labels.append(outcome(
        radar, "2026-02-06T00:00:00Z", "NO_IMPACT_OBSERVED", signal_ids[1]))

    payload = calibrate_risk_outcomes(radar, reversed(labels)).to_dict()
    summaries = {item["signal_id"]: item for item in payload["signals"]}
    assert summaries[signal_ids[0]]["resolved_label_count"] == 5
    assert summaries[signal_ids[0]]["observed_no_impact_rate"]["basis_points"] == 6000
    assert summaries[signal_ids[1]]["resolved_label_count"] == 1
    assert summaries[signal_ids[1]]["observed_no_impact_rate"]["status"] == (
        "INSUFFICIENT_RESOLVED_LABELS")
    assert summaries[signal_ids[1]]["observed_no_impact_rate"]["basis_points"] is None
    assert payload["coverage"]["labeled_signal_count"] == 2


def test_outcome_calibration_bindings_times_and_enums_fail_closed():
    radar = rank_breaking_risks([
        observation("2026-01-01T00:00:00Z"),
        observation("2026-01-02T00:00:00Z"),
    ])
    good = outcome(radar, "2026-02-01T00:00:00Z")
    cases = [
        (replace(good, radar_hash="0" * 64), "outcome_radar_hash_mismatch"),
        (replace(good, signal_id="0" * 64), "outcome_signal_mismatch"),
        (replace(good, outcome="SAFE"), "invalid_outcome"),
        (replace(good, observed_at="2026-01-02T00:00:00Z"),
         "outcome_precedes_radar_window"),
    ]
    for label, code in cases:
        with pytest.raises(RadarError, match=f"^{code}$"):
            calibrate_risk_outcomes(radar, [label])
    with pytest.raises(RadarError, match="^duplicate_outcome_label$"):
        calibrate_risk_outcomes(radar, [good, good])
    with pytest.raises(RadarError, match="^outcome_label_count_out_of_bounds$"):
        calibrate_risk_outcomes(radar, [])
    malformed = replace(good, signal_id=[])  # type: ignore[arg-type]
    with pytest.raises(RadarError, match="^invalid_outcome_label$"):
        calibrate_risk_outcomes(radar, [malformed])
    forged = RiskRadar(json.dumps({"radar_version": "forged"}))
    with pytest.raises(RadarError, match="^invalid_risk_radar$"):
        calibrate_risk_outcomes(forged, [good])


def test_outcome_calibration_does_not_copy_contract_values():
    radar = rank_breaking_risks([
        observation("2026-01-01T00:00:00Z"),
        observation("2026-01-02T00:00:00Z"),
    ])
    report = calibrate_risk_outcomes(
        radar, [outcome(radar, "2026-02-01T00:00:00Z")])
    assert "/items" not in report.payload_json
    assert "old_value" not in report.payload_json
    assert "new_value" not in report.payload_json
