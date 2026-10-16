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
MIN_OBSERVATIONS = 2
MAX_OBSERVATIONS = 64
MAX_SIGNALS = 128
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
