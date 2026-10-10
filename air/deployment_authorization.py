"""Read-only exact-evidence execution preflight. Never deployment authority.

A historical human approval is not a deployment permission. An eventual executor
must independently revalidate the same evidence immediately before acting.
"""
from dataclasses import dataclass
from hashlib import sha256
import json

from .approval_review import prepare_review
from .final_approval import _bounded_text, _scope, load_final_approval
from .postgres import canonical_json

VERSION = "air-execution-boundary-v1"
PURPOSE = "READ_ONLY_PREFLIGHT_NO_DEPLOYMENT_EXECUTION"


class ExecutionBoundaryError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionBoundary:
    """Deterministic read-only receipt, NOT a bearer token or execution authority."""
    payload: str

    @property
    def content_hash(self):
        return sha256(self.payload.encode("utf-8")).hexdigest()


def prepare_execution_boundary(tx, approval_id, proposal_id, *,
                               proposal_hash, revision, current_impact_id,
                               verification_id, verification_hash, fixture_hash,
                               review_hash, environment, integration_id,
                               mapping_id, scope):
    """Recheck exact human approval, current proposal and target without writes.

    The caller supplies authoritative current impact. AIR cannot infer external
    deployment policy; this receipt is not an authorization to execute.
    """
    try:
        if type(revision) is not int or revision < 1:
            raise ExecutionBoundaryError("invalid_revision")
        record = load_final_approval(tx, approval_id)
        approved = json.loads(record["payload"])
        if not isinstance(approved, dict):
            raise ExecutionBoundaryError("malformed_approval")
        target = {
            "environment": _bounded_text(environment, "environment", 128),
            "integration_id": _bounded_text(integration_id, "integration_id", 256),
            "mapping_id": _bounded_text(mapping_id, "mapping_id", 256),
            "scope": _scope(scope),
        }
        if (approved.get("confirmed") is not True
                or type(approved.get("reviewer")) is not str
                or not approved["reviewer"].startswith("human:")
                or not approved["reviewer"][6:]
                or approved.get("tenant_id") != str(tx.tenant_id)
                or approved.get("target") != target
                or approved.get("proposal", {}).get("artifact_id") != str(proposal_id)
                or approved.get("proposal", {}).get("artifact_hash") != proposal_hash
                or type(approved.get("revision")) is not int
                or approved.get("revision") != revision
                or approved.get("verification", {}).get("artifact_id") != str(verification_id)
                or approved.get("verification", {}).get("artifact_hash") != verification_hash
                or approved.get("fixture_hash") != fixture_hash
                or approved.get("review_hash") != review_hash):
            raise ExecutionBoundaryError("approval_or_target_mismatch")
        review = prepare_review(
            tx, proposal_id, proposal_hash=proposal_hash, revision=revision,
            current_impact_id=current_impact_id, verification_id=verification_id,
            verification_hash=verification_hash, fixture_hash=fixture_hash)
        if review.content_hash != review_hash or approved.get("review_payload") != review.payload:
            raise ExecutionBoundaryError("stale_or_substituted_review")
        body = json.loads(review.payload)
        if not isinstance(body, dict):
            raise ExecutionBoundaryError("malformed_review")
        for field in ("proposal", "revision", "prior_proposal_decision",
                      "impact", "change_evidence", "sandbox", "verification",
                      "fixture_hash"):
            if approved.get(field) != body.get(field):
                raise ExecutionBoundaryError("evidence_binding_mismatch")
        dependency = body["impact_item"]["dependency"]
        if (target["integration_id"] != str(dependency["integration_id"])
                or target["mapping_id"] != str(dependency["mapping_id"])
                or str(current_impact_id) != body["impact"]["artifact_id"]):
            raise ExecutionBoundaryError("current_target_or_impact_mismatch")
        receipt = {
            "version": VERSION, "purpose": PURPOSE,
            "tenant_id": str(tx.tenant_id),
            "approval": {"artifact_id": str(record["artifact_id"]),
                         "artifact_hash": record["content_hash"]},
            "proposal": body["proposal"], "revision": revision,
            "verification": body["verification"], "review_hash": review_hash,
            "target": target,
        }
        return ExecutionBoundary(canonical_json(receipt))
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        raise ExecutionBoundaryError("execution_boundary_rejected") from exc
