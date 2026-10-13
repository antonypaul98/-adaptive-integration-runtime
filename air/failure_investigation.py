"""Deterministic, privacy-conscious investigation of recorded replay failures.

This module explains what existing replay evidence proves.  It does not infer a
root cause, execute a repair, call an external system, or grant approval.
"""

from dataclasses import dataclass
from hashlib import sha256
import json

from . import replay_verification as replay
from .postgres import canonical_json


VERSION = "air-failure-investigation-v1"


@dataclass(frozen=True)
class FailureInvestigation:
    """Canonical investigation report with a stable content identity."""

    payload_json: str

    def to_dict(self) -> dict:
        return json.loads(self.payload_json)

    @property
    def content_hash(self) -> str:
        return sha256(self.payload_json.encode("utf-8")).hexdigest()


def investigate_replay(state: object, fixture: object) -> FailureInvestigation:
    """Explain exact recorded projection mismatches without exposing values.

    Validation and resource limits are inherited from the accepted replay
    boundary.  Findings contain only case identifiers and already-produced
    hashes; raw state, paths, expected values, and exception details are absent.
    """

    normalized = replay.normalize_fixture(fixture)
    result = replay.compare(state, normalized)
    fixture_hash = replay.digest(normalized)
    findings = []
    for case in result["cases"]:
        if case["matches"]:
            continue
        evidence = {
            "actual_hash": case["actual_hash"],
            "expected_hash": case["expected_hash"],
        }
        identity = {
            "fixture_hash": fixture_hash,
            "case_id": case["case_id"],
            "code": "RECORDED_VALUE_MISMATCH",
            "evidence": evidence,
        }
        findings.append({
            "finding_id": sha256(canonical_json(identity).encode("utf-8")).hexdigest(),
            "case_id": case["case_id"],
            "code": "RECORDED_VALUE_MISMATCH",
            "confidence": "CONFIRMED",
            "evidence": evidence,
            "explanation": (
                "The bounded recorded projection differs from its exact expected value."
            ),
        })

    findings.sort(key=lambda finding: (finding["case_id"], finding["finding_id"]))
    payload = {
        "investigation_version": VERSION,
        "source": {
            "kind": "bounded_replay_result",
            "replay_version": replay.VERSION,
            "fixture_hash": fixture_hash,
            "status": result["status"],
        },
        "findings": findings,
        "coverage": {
            "analyzed_cases": len(result["cases"]),
            "failing_cases": len(findings),
            "scope": "recorded_projection_cases_only",
            "root_cause_coverage": "NOT_ESTABLISHED",
        },
        "uncertainty": [
            "A value mismatch does not identify which component caused the difference.",
            "Passing recorded cases do not prove unrecorded behavior is safe.",
        ],
        "review_required": bool(findings),
        "authority": "DIAGNOSTIC_ONLY_NO_REPAIR_OR_EXECUTION_AUTHORITY",
    }
    return FailureInvestigation(canonical_json(payload))
