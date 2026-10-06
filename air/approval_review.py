"""Read-only post-verification review material, never deployment authority."""
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from .postgres import canonical_json
from .repair_proposal import authorization, load_proposal, reference
from .replay_verification import load_verification

VERSION = "air-approval-review-v1"


class ReviewError(ValueError):
    pass


@dataclass(frozen=True)
class ApprovalReview:
    """Canonical immutable presentation data; its digest is not a credential."""

    payload: str

    @property
    def content_hash(self):
        return sha256(self.payload.encode("utf-8")).hexdigest()


def prepare_review(tx, proposal_id, *, proposal_hash, revision, current_impact_id,
                   verification_id, verification_hash, fixture_hash):
    """Build review material only from the exact caller-selected passing fixture.

    Reuses tenant-scoped verified loaders and the proposal supersession lock.
    The caller supplies authoritative current impact and required fixture hash;
    AIR does not infer the newest contract or adequate test coverage. No decision
    is recorded. A future consequential operation must recheck all evidence and
    bind its own explicit human decision to its deployment target and scope.
    """
    for value in (proposal_hash, verification_hash, fixture_hash):
        if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ReviewError("invalid_evidence_hash")
    decision = authorization(tx, proposal_id, proposal_hash=proposal_hash,
                             revision=revision, current_impact_id=current_impact_id)
    proposal = load_proposal(tx, proposal_id)
    verification = load_verification(tx, verification_id)
    p, v = json.loads(proposal["payload"]), json.loads(verification["payload"])
    if (verification["content_hash"] != verification_hash
            or v["proposal"] != reference(proposal) or v["revision"] != revision
            or v["impact"] != p["impact"] or v["change_evidence"] != p["change_evidence"]
            or v["fixture_hash"] != fixture_hash):
        raise ReviewError("verification_binding_mismatch")
    if v["result"]["status"] != "PASS":
        raise ReviewError("verification_not_passed")
    body = {
        "review_version": VERSION,
        "purpose": "REVIEW_ONLY_NO_DEPLOYMENT_AUTHORITY",
        "tenant_id": str(tx.tenant_id),
        "proposal": reference(proposal),
        "revision": revision,
        "proposal_description": p["description"],
        "impact_item": p["impact_item"],
        "impact": p["impact"],
        "change_evidence": p["change_evidence"],
        "prior_proposal_decision": reference(decision),
        "sandbox": v["sandbox"],
        "verification": reference(verification),
        "fixture_hash": fixture_hash,
        "fixture": v["fixture"],
        "result": v["result"],
    }
    return ApprovalReview(canonical_json(body))
