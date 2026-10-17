"""Bounded, offline compatibility-risk ranking from accepted change evidence.

The radar is a deterministic triage baseline, not a probability model.  It
does not fetch future releases, inspect production traffic, or authorize any
repair or deployment.  Unsupported or unlabeled evidence remains visible as
uncertainty instead of being converted into a safety claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Iterable

from .change_intelligence import Change, ChangeSet, Classification, DETECTOR_VERSION
from .postgres import canonical_json


VERSION = "air-breaking-change-radar-v1"
TREND_VERSION = "air-breaking-change-risk-trend-v1"
CALIBRATION_VERSION = "air-breaking-change-outcome-calibration-v1"
MIN_OBSERVATIONS = 2
MAX_OBSERVATIONS = 64
MAX_SIGNALS = 128
MAX_OUTCOME_LABELS = 256
MIN_RESOLVED_LABELS_FOR_RATE = 5
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_HASH = re.compile(r"[0-9a-f]{64}")
_CHANGE_TYPES = frozenset({
    "ADDITIONAL_PROPERTIES_CHANGED", "ADDITIONAL_PROPERTIES_SCHEMA_CHANGED",
    "BOOLEAN_SCHEMA_CHANGED", "ENUM_CONSTRAINT_CHANGED", "ENUM_VALUES_ADDED",
    "ENUM_VALUES_REMOVED", "GLOBAL_SECURITY_CHANGED", "MEDIA_TYPE_ADDED",
    "MEDIA_TYPE_REMOVED", "NULLABILITY_CHANGED", "OPENAPI_VERSION_CHANGED",
    "OPERATION_ADDED", "OPERATION_REMOVED", "OPERATION_SECURITY_CHANGED",
    "PARAMETER_ADDED", "PARAMETER_REMOVED", "PARAMETER_REQUIRED_CHANGED",
    "PARAMETER_SERIALIZATION_CHANGED", "PATH_ADDED", "PATH_REMOVED",
    "PROPERTY_ADDED", "PROPERTY_REMOVED", "PROPERTY_VISIBILITY_CHANGED",
    "REQUEST_BODY_ADDED", "REQUEST_BODY_REMOVED", "REQUEST_BODY_REQUIRED_CHANGED",
    "REQUIRED_PROPERTY_ADDED", "REQUIRED_PROPERTY_REMOVED", "RESPONSE_STATUS_ADDED",
    "RESPONSE_STATUS_REMOVED", "SCHEMA_BOUND_CHANGED", "SCHEMA_COMPONENT_ADDED",
    "SCHEMA_COMPONENT_REMOVED", "SECURITY_SCHEME_ADDED", "SECURITY_SCHEME_CHANGED",
    "SECURITY_SCHEME_REMOVED", "TYPE_CHANGED", "UNSUPPORTED_FIELD_CHANGED",
})
_CONTEXTS = frozenset({"request", "response", "security", "contract", "neutral"})
_SEVERITY = {
    Classification.BREAKING: 55,
    Classification.SECURITY_RELEVANT: 65,
    Classification.REVIEW_REQUIRED: 35,
}
_OUTCOMES = frozenset({
    "IMPACT_CONFIRMED", "NO_IMPACT_OBSERVED", "INCONCLUSIVE",
})


class RadarError(ValueError):
    """Fixed diagnostic codes only; never echo caller evidence."""


@dataclass(frozen=True)
class ChangeObservation:
    """One immutable detector result with caller-supplied source time."""

    observed_at: str
    changes: ChangeSet


@dataclass(frozen=True)
class RiskRadar:
    """Canonical, content-addressed risk triage output."""

    payload_json: str

    def to_dict(self) -> dict:
        return json.loads(self.payload_json)

    @property
    def content_hash(self) -> str:
        return sha256(self.payload_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RiskTrendReport:
    """Canonical comparison of two non-overlapping offline radar windows."""

    payload_json: str

    def to_dict(self) -> dict:
        return json.loads(self.payload_json)

    @property
    def content_hash(self) -> str:
        return sha256(self.payload_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RiskOutcomeLabel:
    """Caller-declared offline outcome bound to an exact radar signal."""

    observed_at: str
    radar_hash: str
    signal_id: str
    outcome: str


@dataclass(frozen=True)
class OutcomeCalibrationReport:
    """Canonical summary of bounded caller-declared outcome evidence."""

    payload_json: str

    def to_dict(self) -> dict:
        return json.loads(self.payload_json)

    @property
    def content_hash(self) -> str:
        return sha256(self.payload_json.encode("utf-8")).hexdigest()


def _time(value: object) -> datetime:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise RadarError("invalid_observed_at")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise RadarError("invalid_observed_at") from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise RadarError("invalid_observed_at")
    return parsed


def _validate_change_set(value: object) -> ChangeSet:
    if not isinstance(value, ChangeSet) or value.version != DETECTOR_VERSION:
        raise RadarError("unsupported_change_evidence")
    try:
        payload = value.to_dict()
        encoded = canonical_json(payload)
        if json.loads(encoded) != payload:
            raise ValueError()
        if (len(value.changes) > 2000
                or not _HASH.fullmatch(value.previous_semantic_hash)
                or not _HASH.fullmatch(value.new_semantic_hash)):
            raise ValueError()
        for change in value.changes:
            if (not isinstance(change, Change)
                    or not isinstance(change.classification, Classification)
                    or change.change_type not in _CHANGE_TYPES
                    or change.context not in _CONTEXTS
                    or not _HASH.fullmatch(change.change_id)):
                raise ValueError()
    except (TypeError, ValueError, json.JSONDecodeError):
        raise RadarError("invalid_change_evidence") from None
    return value


def rank_breaking_risks(observations: Iterable[ChangeObservation]) -> RiskRadar:
    """Rank recurring non-safe signals without asserting future certainty.

    Risk scores are transparent heuristic points in the range 0..95.  They are
    deliberately capped below certainty and must not be read as probabilities.
    """

    try:
        items = tuple(observations)
    except TypeError:
        raise RadarError("invalid_observations") from None
    if not MIN_OBSERVATIONS <= len(items) <= MAX_OBSERVATIONS:
        raise RadarError("observation_count_out_of_bounds")

    validated = []
    identities = set()
    for item in items:
        if not isinstance(item, ChangeObservation):
            raise RadarError("invalid_observation")
        observed = _time(item.observed_at)
        changes = _validate_change_set(item.changes)
        identity = (item.observed_at, changes.content_hash)
        if identity in identities:
            raise RadarError("duplicate_observation")
        identities.add(identity)
        validated.append((observed, item.observed_at, changes))
    validated.sort(key=lambda item: (item[0], item[2].content_hash))

    groups: dict[tuple[str, str, str], dict] = {}
    for index, (_, observed_at, change_set) in enumerate(validated):
        seen = set()
        for change in change_set.changes:
            if change.classification not in _SEVERITY:
                continue
            key = (change.classification.value, change.change_type, change.context)
            group = groups.setdefault(key, {"observation_indexes": set(), "events": 0,
                                             "last_observed_at": observed_at,
                                             "last_index": index})
            group["events"] += 1
            if key not in seen:
                group["observation_indexes"].add(index)
                seen.add(key)
            if index >= group["last_index"]:
                group["last_index"] = index
                group["last_observed_at"] = observed_at
    if len(groups) > MAX_SIGNALS:
        raise RadarError("signal_count_out_of_bounds")

    signals = []
    total = len(validated)
    for key, group in groups.items():
        classification, change_type, context = key
        occurrence_count = len(group["observation_indexes"])
        frequency_points = (25 * occurrence_count) // total
        recency_points = (10 * (group["last_index"] + 1)) // total
        score = min(95, _SEVERITY[Classification(classification)]
                    + frequency_points + recency_points)
        uncertainty = "HIGH" if occurrence_count < 2 else (
            "MEDIUM" if occurrence_count < 4 else "LOWER_BUT_UNQUANTIFIED")
        basis = {
            "classification": classification,
            "change_type": change_type,
            "context": context,
        }
        signals.append({
            "signal_id": sha256(canonical_json(basis).encode("utf-8")).hexdigest(),
            **basis,
            "risk_score": score,
            "score_kind": "HEURISTIC_POINTS_NOT_PROBABILITY",
            "uncertainty": uncertainty,
            "evidence": {
                "observation_count": occurrence_count,
                "event_count": group["events"],
                "last_observed_at": group["last_observed_at"],
            },
        })
    signals.sort(key=lambda signal: (-signal["risk_score"], signal["signal_id"]))

    source_hashes = [entry[2].content_hash for entry in validated]
    payload = {
        "radar_version": VERSION,
        "detector_version": DETECTOR_VERSION,
        "source": {
            "kind": "bounded_offline_change_evidence",
            "observation_count": total,
            "first_observed_at": validated[0][1],
            "last_observed_at": validated[-1][1],
            "evidence_hashes": source_hashes,
        },
        "signals": signals,
        "coverage": {
            "eligible_classifications": sorted(item.value for item in _SEVERITY),
            "ignored_non_breaking_events": sum(
                1 for entry in validated for change in entry[2].changes
                if change.classification == Classification.NON_BREAKING),
            "labeled_outcomes": 0,
            "false_positive_rate": "NOT_MEASURABLE_WITHOUT_LABELED_OUTCOMES",
        },
        "uncertainty": [
            "Scores rank observed detector signals; they are not probabilities.",
            "Historical recurrence does not prove that a future change will occur.",
            "No labeled outcomes are available to estimate false-positive rates.",
            "Unobserved sources, contracts, and unsupported detector semantics are not covered.",
        ],
        "review_required": bool(signals),
        "authority": "DIAGNOSTIC_ONLY_NO_REPAIR_EXECUTION_OR_DEPLOYMENT_AUTHORITY",
    }
    return RiskRadar(canonical_json(payload))


def compare_risk_windows(
    baseline: Iterable[ChangeObservation],
    candidate: Iterable[ChangeObservation],
) -> RiskTrendReport:
    """Compare two bounded historical windows without predicting an outcome.

    Both windows pass the same fail-closed validation as ``rank_breaking_risks``.
    They must be strictly ordered and non-overlapping so a caller cannot present
    the same time period as independent trend evidence.
    """

    baseline_radar = rank_breaking_risks(baseline)
    candidate_radar = rank_breaking_risks(candidate)
    baseline_payload = baseline_radar.to_dict()
    candidate_payload = candidate_radar.to_dict()
    baseline_source = baseline_payload["source"]
    candidate_source = candidate_payload["source"]
    if _time(baseline_source["last_observed_at"]) >= _time(
        candidate_source["first_observed_at"]
    ):
        raise RadarError("risk_windows_not_strictly_ordered")

    baseline_signals = {
        signal["signal_id"]: signal for signal in baseline_payload["signals"]
    }
    candidate_signals = {
        signal["signal_id"]: signal for signal in candidate_payload["signals"]
    }
    trends = []
    for signal_id in sorted(set(baseline_signals) | set(candidate_signals)):
        before = baseline_signals.get(signal_id)
        after = candidate_signals.get(signal_id)
        before_score = before["risk_score"] if before else 0
        after_score = after["risk_score"] if after else 0
        delta = after_score - before_score
        if before is None:
            direction = "NEWLY_OBSERVED"
        elif after is None:
            direction = "NOT_OBSERVED_IN_CANDIDATE_WINDOW"
        elif delta > 0:
            direction = "RISING_HEURISTIC_POINTS"
        elif delta < 0:
            direction = "FALLING_HEURISTIC_POINTS"
        else:
            direction = "UNCHANGED_HEURISTIC_POINTS"
        source = after or before
        trends.append({
            "signal_id": signal_id,
            "classification": source["classification"],
            "change_type": source["change_type"],
            "context": source["context"],
            "baseline_score": before_score,
            "candidate_score": after_score,
            "score_delta": delta,
            "direction": direction,
            "score_kind": "HEURISTIC_POINTS_NOT_PROBABILITY",
            "candidate_uncertainty": (
                after["uncertainty"] if after else "NOT_OBSERVED"
            ),
        })
    trends.sort(key=lambda trend: (-abs(trend["score_delta"]), trend["signal_id"]))

    payload = {
        "trend_version": TREND_VERSION,
        "radar_version": VERSION,
        "detector_version": DETECTOR_VERSION,
        "source": {
            "kind": "bounded_offline_risk_window_comparison",
            "baseline_radar_hash": baseline_radar.content_hash,
            "candidate_radar_hash": candidate_radar.content_hash,
            "baseline": baseline_source,
            "candidate": candidate_source,
        },
        "trends": trends,
        "coverage": {
            "baseline_signal_count": len(baseline_signals),
            "candidate_signal_count": len(candidate_signals),
            "compared_signal_count": len(trends),
            "labeled_outcomes": 0,
            "false_positive_rate": "NOT_MEASURABLE_WITHOUT_LABELED_OUTCOMES",
        },
        "uncertainty": [
            "Score deltas compare bounded historical windows; they do not predict an outcome.",
            "Different observation counts and source coverage can change heuristic scores.",
            "A missing candidate signal is not evidence that the underlying risk is absent.",
            "No labeled outcomes are available to calibrate false-positive rates.",
        ],
        "review_required": bool(trends),
        "authority": "DIAGNOSTIC_ONLY_NO_REPAIR_EXECUTION_OR_DEPLOYMENT_AUTHORITY",
    }
    return RiskTrendReport(canonical_json(payload))


def calibrate_risk_outcomes(
    radar: RiskRadar,
    labels: Iterable[RiskOutcomeLabel],
) -> OutcomeCalibrationReport:
    """Summarize bounded outcome labels without treating them as ground truth."""

    if not isinstance(radar, RiskRadar):
        raise RadarError("invalid_risk_radar")
    try:
        radar_payload = radar.to_dict()
        if (canonical_json(radar_payload) != radar.payload_json
                or radar_payload["radar_version"] != VERSION
                or radar_payload["detector_version"] != DETECTOR_VERSION
                or radar_payload["source"]["kind"] != "bounded_offline_change_evidence"
                or radar_payload["authority"]
                != "DIAGNOSTIC_ONLY_NO_REPAIR_EXECUTION_OR_DEPLOYMENT_AUTHORITY"):
            raise ValueError()
        last_radar_time = _time(radar_payload["source"]["last_observed_at"])
        signal_ids = {signal["signal_id"] for signal in radar_payload["signals"]}
        if (len(signal_ids) != len(radar_payload["signals"])
                or len(signal_ids) > MAX_SIGNALS
                or any(not _HASH.fullmatch(value) for value in signal_ids)):
            raise ValueError()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise RadarError("invalid_risk_radar") from None

    try:
        items = tuple(labels)
    except TypeError:
        raise RadarError("invalid_outcome_labels") from None
    if not 1 <= len(items) <= MAX_OUTCOME_LABELS:
        raise RadarError("outcome_label_count_out_of_bounds")

    validated = []
    identities = set()
    for item in items:
        if not isinstance(item, RiskOutcomeLabel):
            raise RadarError("invalid_outcome_label")
        if (not isinstance(item.radar_hash, str)
                or not isinstance(item.signal_id, str)
                or not isinstance(item.outcome, str)):
            raise RadarError("invalid_outcome_label")
        observed = _time(item.observed_at)
        if observed <= last_radar_time:
            raise RadarError("outcome_precedes_radar_window")
        if item.radar_hash != radar.content_hash:
            raise RadarError("outcome_radar_hash_mismatch")
        if item.signal_id not in signal_ids:
            raise RadarError("outcome_signal_mismatch")
        if item.outcome not in _OUTCOMES:
            raise RadarError("invalid_outcome")
        identity = (item.observed_at, item.signal_id)
        if identity in identities:
            raise RadarError("duplicate_outcome_label")
        identities.add(identity)
        validated.append(item)
    validated.sort(key=lambda item: (
        item.observed_at, item.signal_id, item.outcome,
    ))

    counts = {
        signal_id: {outcome: 0 for outcome in sorted(_OUTCOMES)}
        for signal_id in signal_ids
    }
    label_receipts = []
    for item in validated:
        counts[item.signal_id][item.outcome] += 1
        basis = {
            "observed_at": item.observed_at,
            "radar_hash": item.radar_hash,
            "signal_id": item.signal_id,
            "outcome": item.outcome,
        }
        label_receipts.append({
            "label_id": sha256(canonical_json(basis).encode("utf-8")).hexdigest(),
            **basis,
        })

    confirmed = sum(value["IMPACT_CONFIRMED"] for value in counts.values())
    no_impact = sum(value["NO_IMPACT_OBSERVED"] for value in counts.values())
    inconclusive = sum(value["INCONCLUSIVE"] for value in counts.values())
    resolved = confirmed + no_impact
    rate_available = resolved >= MIN_RESOLVED_LABELS_FOR_RATE
    summaries = []
    for signal_id in sorted(signal_ids):
        value = counts[signal_id]
        if sum(value.values()):
            summaries.append({"signal_id": signal_id, **value})

    payload = {
        "calibration_version": CALIBRATION_VERSION,
        "radar_version": VERSION,
        "detector_version": DETECTOR_VERSION,
        "source": {
            "kind": "bounded_caller_declared_offline_outcomes",
            "radar_hash": radar.content_hash,
            "radar_last_observed_at": radar_payload["source"]["last_observed_at"],
            "label_set_hash": sha256(
                canonical_json({"labels": label_receipts}).encode("utf-8")
            ).hexdigest(),
        },
        "labels": label_receipts,
        "signals": summaries,
        "coverage": {
            "radar_signal_count": len(signal_ids),
            "labeled_signal_count": len(summaries),
            "unlabeled_signal_count": len(signal_ids) - len(summaries),
            "label_count": len(validated),
            "resolved_label_count": resolved,
            "inconclusive_label_count": inconclusive,
        },
        "observed_no_impact_rate": {
            "status": "AVAILABLE" if rate_available
            else "INSUFFICIENT_RESOLVED_LABELS",
            "minimum_resolved_labels": MIN_RESOLVED_LABELS_FOR_RATE,
            "numerator": no_impact,
            "denominator": resolved,
            "basis_points": (no_impact * 10000) // resolved
            if rate_available else None,
            "kind": "DESCRIPTIVE_CALLER_LABEL_RATE_NOT_PROBABILITY",
        },
        "uncertainty": [
            "Outcome labels are caller declarations and are not independently verified.",
            "No-impact labels do not prove that a change was safe or harmless.",
            "Unlabeled and inconclusive signals are excluded from the descriptive rate.",
            "The rate is not a forecast, probability, causal estimate, or authorization.",
        ],
        "review_required": True,
        "authority": "DIAGNOSTIC_ONLY_NO_REPAIR_EXECUTION_OR_DEPLOYMENT_AUTHORITY",
    }
    return OutcomeCalibrationReport(canonical_json(payload))
