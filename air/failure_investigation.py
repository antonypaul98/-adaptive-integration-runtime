"""Deterministic, privacy-conscious investigation of recorded replay failures.

This module explains what existing replay evidence proves.  It does not infer a
root cause, execute a repair, call an external system, or grant approval.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Iterable

from . import replay_verification as replay
from .change_intelligence import ChangeSet
from .dependency_impact import IMPACT_VERSION, WORKFLOW_VERSION, ImpactReport
from .postgres import canonical_json


VERSION = "air-failure-investigation-v1"
RECORD_VERSION = "air-failure-investigation-record-v1"
CORRELATION_VERSION = "air-failure-correlation-v1"
CORRELATION_RECORD_VERSION = "air-failure-correlation-record-v1"
MAX_CANDIDATE_LINKS = 128
_HASH = re.compile(r"[0-9a-f]{64}")


class InvestigationError(ValueError):
    """Fixed diagnostic codes only; never echo evidence or private input."""


@dataclass(frozen=True)
class FailureInvestigation:
    """Canonical investigation report with a stable content identity."""

    payload_json: str

    def to_dict(self) -> dict:
        return json.loads(self.payload_json)

    @property
    def content_hash(self) -> str:
        return sha256(self.payload_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidateLink:
    """A caller-declared association, not an inferred or proven cause."""

    case_id: str
    impact_id: str
    basis: str = "DECLARED_TEST_DEPENDENCY"

    def __post_init__(self) -> None:
        if (not isinstance(self.case_id, str) or not self.case_id
                or len(self.case_id) > 128 or any(ord(char) < 32 for char in self.case_id)):
            raise InvestigationError("invalid_case_id")
        if not isinstance(self.impact_id, str) or not _HASH.fullmatch(self.impact_id):
            raise InvestigationError("invalid_impact_id")
        if self.basis != "DECLARED_TEST_DEPENDENCY":
            raise InvestigationError("unsupported_correlation_basis")


@dataclass(frozen=True)
class CandidateCorrelation:
    """Canonical, redacted candidate-cause correlations with stable identity."""

    payload_json: str

    def to_dict(self) -> dict:
        return json.loads(self.payload_json)

    @property
    def content_hash(self) -> str:
        return sha256(self.payload_json.encode("utf-8")).hexdigest()


def _investigate_result(fixture_hash: object, result: object) -> FailureInvestigation:
    """Build a redacted report from validated replay-result evidence."""
    if not isinstance(fixture_hash, str) or not _HASH.fullmatch(fixture_hash):
        raise InvestigationError("invalid_fixture_hash")
    if (not isinstance(result, dict) or set(result) != {"status", "cases"}
            or result["status"] not in {"PASS", "FAIL"}
            or not isinstance(result["cases"], list)
            or not 1 <= len(result["cases"]) <= replay.MAX_CASES):
        raise InvestigationError("invalid_replay_result")
    seen = set()
    findings = []
    for case in result["cases"]:
        if (not isinstance(case, dict)
                or set(case) != {"case_id", "actual_hash", "expected_hash", "matches"}
                or not isinstance(case["case_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", case["case_id"])
                or case["case_id"] in seen
                or any(not isinstance(case[name], str) or not _HASH.fullmatch(case[name])
                       for name in ("actual_hash", "expected_hash"))
                or type(case["matches"]) is not bool
                or case["matches"] != (case["actual_hash"] == case["expected_hash"])):
            raise InvestigationError("invalid_replay_case")
        seen.add(case["case_id"])
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
    if (result["status"] == "FAIL") != bool(findings):
        raise InvestigationError("inconsistent_replay_result")
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


def investigate_replay(state: object, fixture: object) -> FailureInvestigation:
    """Explain exact recorded projection mismatches without exposing values.

    Validation and resource limits are inherited from the accepted replay
    boundary.  Findings contain only case identifiers and already-produced
    hashes; raw state, paths, expected values, and exception details are absent.
    """

    normalized = replay.normalize_fixture(fixture)
    return _investigate_result(replay.digest(normalized), replay.compare(state, normalized))


def persist_investigation(tx, verification_id: object) -> dict:
    """Persist a redacted report bound to exact immutable replay evidence.

    Historical replay evidence is diagnostic input only.  This function does
    not re-run a proposal, authorize a repair, or grant deployment authority.
    """
    try:
        verification = replay.load_verification(tx, verification_id)
        source = json.loads(verification["payload"])
        report = _investigate_result(source["fixture_hash"], source["result"])
        payload = {
            "tenant_id": str(tx.tenant_id),
            "investigation_record_version": RECORD_VERSION,
            "verification": {
                "artifact_id": str(verification["artifact_id"]),
                "artifact_hash": verification["content_hash"],
            },
            "report_hash": report.content_hash,
            "report_payload": report.payload_json,
        }
        key = _digest(payload)
        return tx.put("failure_investigation", key, payload)
    except replay.ReplayError as exc:
        raise InvestigationError("verification_not_found_or_invalid") from exc
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, InvestigationError):
            raise
        raise InvestigationError("investigation_persistence_rejected") from exc


def load_investigation(tx, identity: object) -> dict:
    """Reload and revalidate tenant-bound immutable investigation evidence."""
    try:
        record = tx.get_by_id(identity, kind="failure_investigation")
    except (TypeError, ValueError):
        record = None
    if record is None or record["tenant_id"] != tx.tenant_id:
        raise InvestigationError("not_found_or_not_authorized")
    try:
        payload = json.loads(record["payload"])
        verification = replay.load_verification(
            tx, payload["verification"]["artifact_id"])
        source = json.loads(verification["payload"])
        report = _investigate_result(source["fixture_hash"], source["result"])
        expected = {
            "tenant_id": str(tx.tenant_id),
            "investigation_record_version": RECORD_VERSION,
            "verification": {
                "artifact_id": str(verification["artifact_id"]),
                "artifact_hash": verification["content_hash"],
            },
            "report_hash": report.content_hash,
            "report_payload": report.payload_json,
        }
        expected_json = canonical_json(expected)
        if (record["payload"] != expected_json
                or record["idempotency_key"] != _digest(expected)
                or record["content_hash"] != _digest(expected)):
            raise InvestigationError("invalid_persisted_investigation")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, replay.ReplayError) as exc:
        if isinstance(exc, InvestigationError):
            raise
        raise InvestigationError("invalid_persisted_investigation") from exc
    return record


def _digest(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validated_findings(investigation: FailureInvestigation) -> tuple[dict, dict[str, dict]]:
    if not isinstance(investigation, FailureInvestigation):
        raise InvestigationError("invalid_investigation")
    try:
        payload = investigation.to_dict()
        if canonical_json(payload) != investigation.payload_json:
            raise InvestigationError("noncanonical_investigation")
    except (TypeError, ValueError, json.JSONDecodeError):
        raise InvestigationError("invalid_investigation") from None
    if (not isinstance(payload, dict)
            or set(payload) != {"investigation_version", "source", "findings", "coverage",
                                "uncertainty", "review_required", "authority"}
            or payload["investigation_version"] != VERSION
            or payload["authority"] != "DIAGNOSTIC_ONLY_NO_REPAIR_OR_EXECUTION_AUTHORITY"):
        raise InvestigationError("unsupported_investigation")
    source = payload["source"]
    if (not isinstance(source, dict)
            or set(source) != {"kind", "replay_version", "fixture_hash", "status"}
            or source["kind"] != "bounded_replay_result"
            or source["replay_version"] != replay.VERSION
            or not isinstance(source["fixture_hash"], str)
            or not _HASH.fullmatch(source["fixture_hash"])
            or source["status"] not in {"PASS", "FAIL"}):
        raise InvestigationError("unsupported_investigation_source")
    if not isinstance(payload["findings"], list):
        raise InvestigationError("invalid_findings")
    findings = {}
    for finding in payload["findings"]:
        if (not isinstance(finding, dict)
                or set(finding) != {"finding_id", "case_id", "code", "confidence",
                                    "evidence", "explanation"}
                or finding["code"] != "RECORDED_VALUE_MISMATCH"
                or finding["confidence"] != "CONFIRMED"
                or not isinstance(finding["case_id"], str)
                or not isinstance(finding["evidence"], dict)
                or set(finding["evidence"]) != {"actual_hash", "expected_hash"}
                or any(not isinstance(value, str) or not _HASH.fullmatch(value)
                       for value in finding["evidence"].values())):
            raise InvestigationError("invalid_finding")
        identity = {"fixture_hash": source["fixture_hash"], "case_id": finding["case_id"],
                    "code": finding["code"], "evidence": finding["evidence"]}
        if finding["finding_id"] != _digest(identity) or finding["case_id"] in findings:
            raise InvestigationError("invalid_finding_identity")
        findings[finding["case_id"]] = finding
    if ((source["status"] == "FAIL") != bool(findings)
            or payload["review_required"] != bool(findings)):
        raise InvestigationError("inconsistent_investigation")
    return payload, findings


def _validated_impacts(changes: ChangeSet, report: ImpactReport) -> tuple[dict, dict[str, dict]]:
    if not isinstance(changes, ChangeSet) or not isinstance(report, ImpactReport):
        raise InvestigationError("invalid_lifecycle_evidence")
    try:
        payload = report.to_dict()
        if canonical_json(payload) != report.payload_json:
            raise InvestigationError("noncanonical_impact_report")
    except (TypeError, ValueError, json.JSONDecodeError):
        raise InvestigationError("invalid_impact_report") from None
    if (not isinstance(payload, dict)
            or payload.get("impact_version") not in {IMPACT_VERSION, WORKFLOW_VERSION}
            or payload.get("change_set_hash") != changes.content_hash
            or not isinstance(payload.get("impacts"), list)):
        raise InvestigationError("unbound_impact_report")
    if not isinstance(payload.get("downstream_impacts", []), list):
        raise InvestigationError("invalid_impact_report")
    values = payload["impacts"] + payload.get("downstream_impacts", [])
    impacts = {}
    change_ids = {change.change_id for change in changes.changes}
    for impact in values:
        if (not isinstance(impact, dict)
                or not isinstance(impact.get("impact_id"), str)
                or not _HASH.fullmatch(impact["impact_id"])
                or impact.get("change_id") not in change_ids
                or impact.get("classification") not in {
                    "BREAKING", "SECURITY_RELEVANT", "REVIEW_REQUIRED"
                }
                or impact.get("match") not in {
                    "LOCATION_OVERLAP", "SCHEMA_REVIEW", "OPERATION_REVIEW",
                    "GLOBAL_SECURITY_REVIEW", "TRANSITIVE_REVIEW"
                }):
            raise InvestigationError("invalid_impact")
        identity = {key: value for key, value in impact.items() if key != "impact_id"}
        if impact["impact_id"] != _digest(identity) or impact["impact_id"] in impacts:
            raise InvestigationError("invalid_impact_identity")
        impacts[impact["impact_id"]] = impact
    return payload, impacts


def _validated_persisted_impacts(record: dict) -> tuple[dict, dict[str, dict]]:
    """Validate the redacted impact analysis from already-verified evidence."""
    try:
        envelope = json.loads(record["payload"])
        payload = envelope["analysis"]
        report = ImpactReport(canonical_json(payload))
        if (envelope["impact_hash"] != report.content_hash
                or payload.get("impact_version") not in {IMPACT_VERSION, WORKFLOW_VERSION}
                or not isinstance(payload.get("change_set_hash"), str)
                or not _HASH.fullmatch(payload["change_set_hash"])
                or not isinstance(payload.get("impacts"), list)
                or not isinstance(payload.get("downstream_impacts", []), list)):
            raise InvestigationError("invalid_impact_evidence")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise InvestigationError("invalid_impact_evidence") from None
    impacts = {}
    for impact in payload["impacts"] + payload.get("downstream_impacts", []):
        if (not isinstance(impact, dict)
                or not isinstance(impact.get("impact_id"), str)
                or not _HASH.fullmatch(impact["impact_id"])
                or not isinstance(impact.get("change_id"), str)
                or not _HASH.fullmatch(impact["change_id"])
                or impact.get("classification") not in {
                    "BREAKING", "SECURITY_RELEVANT", "REVIEW_REQUIRED"
                }
                or impact.get("match") not in {
                    "LOCATION_OVERLAP", "SCHEMA_REVIEW", "OPERATION_REVIEW",
                    "GLOBAL_SECURITY_REVIEW", "TRANSITIVE_REVIEW"
                }):
            raise InvestigationError("invalid_impact")
        identity = {key: value for key, value in impact.items() if key != "impact_id"}
        if impact["impact_id"] != _digest(identity) or impact["impact_id"] in impacts:
            raise InvestigationError("invalid_impact_identity")
        impacts[impact["impact_id"]] = impact
    return payload, impacts


def _candidate_payload(
    investigation: FailureInvestigation,
    impact_payload: dict,
    impact_hash: str,
    impacts: dict[str, dict],
    links: Iterable[CandidateLink],
) -> CandidateCorrelation:
    investigation_payload, findings = _validated_findings(investigation)
    normalized = {}
    try:
        iterator = iter(links)
    except TypeError:
        raise InvestigationError("invalid_candidate_links") from None
    for index, link in enumerate(iterator):
        if index >= MAX_CANDIDATE_LINKS:
            raise InvestigationError("candidate_link_limit")
        if not isinstance(link, CandidateLink):
            raise InvestigationError("invalid_candidate_link")
        if link.case_id not in findings:
            raise InvestigationError("case_not_failing")
        if link.impact_id not in impacts:
            raise InvestigationError("impact_not_found")
        normalized[(link.case_id, link.impact_id, link.basis)] = link

    source = {
        "investigation_hash": investigation.content_hash,
        "fixture_hash": investigation_payload["source"]["fixture_hash"],
        "change_set_hash": impact_payload["change_set_hash"],
        "impact_report_hash": impact_hash,
        "impact_version": impact_payload["impact_version"],
    }
    candidates = []
    for key in sorted(normalized):
        link = normalized[key]
        impact = impacts[link.impact_id]
        evidence = {
            "finding_id": findings[link.case_id]["finding_id"],
            "impact_id": link.impact_id,
            "change_id": impact["change_id"],
        }
        identity = {"source": source, "case_id": link.case_id, "basis": link.basis,
                    "evidence": evidence}
        candidates.append({
            "candidate_id": _digest(identity),
            "case_id": link.case_id,
            "basis": link.basis,
            "impact_match": impact["match"],
            "classification": impact["classification"],
            "confidence": "SUPPORTED_CORRELATION_NOT_CAUSAL_PROOF",
            "evidence": evidence,
        })

    linked_cases = {candidate["case_id"] for candidate in candidates}
    payload = {
        "correlation_version": CORRELATION_VERSION,
        "source": source,
        "candidates": candidates,
        "coverage": {
            "failing_cases": len(findings),
            "linked_failing_cases": len(linked_cases),
            "declared_links": len(candidates),
            "unmatched_case_ids": sorted(set(findings) - linked_cases),
            "scope": "caller_declared_case_to_impact_links_only",
            "root_cause_coverage": "NOT_ESTABLISHED",
        },
        "uncertainty": [
            "A declared dependency correlation is not evidence that a change caused a failure.",
            "Unregistered dependencies, unchanged behavior, environment, data, and timing remain outside this correlation.",
        ],
        "review_required": bool(findings),
        "authority": "DIAGNOSTIC_ONLY_NO_REPAIR_OR_EXECUTION_AUTHORITY",
    }
    return CandidateCorrelation(canonical_json(payload))


def correlate_candidates(
    investigation: FailureInvestigation,
    changes: ChangeSet,
    impact_report: ImpactReport,
    links: Iterable[CandidateLink],
) -> CandidateCorrelation:
    """Correlate explicit case/impact links without claiming causal proof.

    The caller must supply every association. AIR validates and binds those
    associations to exact immutable artifacts; it does not guess from names,
    paths, payload values, timing, or model output.
    """

    impact_payload, impacts = _validated_impacts(changes, impact_report)
    return _candidate_payload(investigation, impact_payload, impact_report.content_hash,
                              impacts, links)


def persist_candidate_correlation(
    tx,
    investigation_id: object,
    impact_id: object,
    links: Iterable[CandidateLink],
) -> dict:
    """Persist caller-declared correlation evidence with exact tenant bindings."""
    from . import dependency_impact as dependency

    try:
        investigation_record = load_investigation(tx, investigation_id)
        impact_record = dependency.load_impact(tx, impact_id)
        investigation_envelope = json.loads(investigation_record["payload"])
        investigation = FailureInvestigation(investigation_envelope["report_payload"])
        impact_envelope = json.loads(impact_record["payload"])
        _validate_persisted_lifecycle_binding(
            tx, investigation_envelope, impact_record, impact_envelope)
        impact_payload, impacts = _validated_persisted_impacts(impact_record)
        correlation = _candidate_payload(
            investigation, impact_payload, impact_envelope["impact_hash"], impacts, links
        )
        declared_links = [
            {"case_id": candidate["case_id"], "impact_id": candidate["evidence"]["impact_id"],
             "basis": candidate["basis"]}
            for candidate in correlation.to_dict()["candidates"]
        ]
        payload = {
            "tenant_id": str(tx.tenant_id),
            "correlation_record_version": CORRELATION_RECORD_VERSION,
            "investigation": {
                "artifact_id": str(investigation_record["artifact_id"]),
                "artifact_hash": investigation_record["content_hash"],
            },
            "impact": {
                "artifact_id": str(impact_record["artifact_id"]),
                "artifact_hash": impact_record["content_hash"],
            },
            "declared_links": declared_links,
            "correlation_hash": correlation.content_hash,
            "correlation_payload": correlation.payload_json,
        }
        return tx.put("failure_candidate_correlation", _digest(payload), payload)
    except InvestigationError:
        raise
    except dependency.ImpactError as exc:
        raise InvestigationError("impact_not_found_or_invalid") from exc
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InvestigationError("correlation_persistence_rejected") from exc


def load_candidate_correlation(tx, identity: object) -> dict:
    """Reload and recompute immutable candidate-correlation evidence."""
    from . import dependency_impact as dependency

    try:
        record = tx.get_by_id(identity, kind="failure_candidate_correlation")
    except (TypeError, ValueError):
        record = None
    if record is None or record["tenant_id"] != tx.tenant_id:
        raise InvestigationError("not_found_or_not_authorized")
    try:
        stored = json.loads(record["payload"])
        investigation_record = load_investigation(
            tx, stored["investigation"]["artifact_id"])
        impact_record = dependency.load_impact(tx, stored["impact"]["artifact_id"])
        investigation_envelope = json.loads(investigation_record["payload"])
        investigation = FailureInvestigation(investigation_envelope["report_payload"])
        impact_envelope = json.loads(impact_record["payload"])
        _validate_persisted_lifecycle_binding(
            tx, investigation_envelope, impact_record, impact_envelope)
        impact_payload, impacts = _validated_persisted_impacts(impact_record)
        links = [CandidateLink(**value) for value in stored["declared_links"]]
        correlation = _candidate_payload(
            investigation, impact_payload, impact_envelope["impact_hash"], impacts, links)
        declared_links = [
            {"case_id": candidate["case_id"], "impact_id": candidate["evidence"]["impact_id"],
             "basis": candidate["basis"]}
            for candidate in correlation.to_dict()["candidates"]
        ]
        expected = {
            "tenant_id": str(tx.tenant_id),
            "correlation_record_version": CORRELATION_RECORD_VERSION,
            "investigation": {
                "artifact_id": str(investigation_record["artifact_id"]),
                "artifact_hash": investigation_record["content_hash"],
            },
            "impact": {
                "artifact_id": str(impact_record["artifact_id"]),
                "artifact_hash": impact_record["content_hash"],
            },
            "declared_links": declared_links,
            "correlation_hash": correlation.content_hash,
            "correlation_payload": correlation.payload_json,
        }
        if (record["payload"] != canonical_json(expected)
                or record["idempotency_key"] != _digest(expected)
                or record["content_hash"] != _digest(expected)):
            raise InvestigationError("invalid_persisted_correlation")
    except InvestigationError:
        raise
    except (dependency.ImpactError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InvestigationError("invalid_persisted_correlation") from exc
    return record


def _validate_persisted_lifecycle_binding(
    tx,
    investigation_envelope: dict,
    impact_record: dict,
    impact_envelope: dict,
) -> None:
    """Require the selected impact to be the replay's exact lifecycle input.

    Loading the verification also recomputes its proposal and sandbox bindings.
    This check then closes the remaining transitive gap from the persisted
    investigation through replay/sandbox to the exact impact and change evidence.
    """
    try:
        verification = replay.load_verification(
            tx, investigation_envelope["verification"]["artifact_id"])
        verification_payload = json.loads(verification["payload"])
        impact_reference = {
            "artifact_id": str(impact_record["artifact_id"]),
            "artifact_hash": impact_record["content_hash"],
        }
        if (verification_payload["impact"] != impact_reference
                or verification_payload["change_evidence"]
                != impact_envelope["change_evidence"]):
            raise InvestigationError("lifecycle_binding_mismatch")
    except InvestigationError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError,
            replay.ReplayError) as exc:
        raise InvestigationError("invalid_lifecycle_binding") from exc
