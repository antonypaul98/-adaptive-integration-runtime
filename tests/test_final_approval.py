import json
import pytest

from air.final_approval import approve, load_final_approval, FinalApprovalError
from test_approval_review import evidence, review
from test_repair_proposal import context


def call(tx, p, v, **changes):
    pb, vb = json.loads(p["payload"]), json.loads(v["payload"])
    r = review(tx, p, v)
    args = dict(proposal_hash=p["content_hash"], revision=pb["revision"],
                current_impact_id=pb["impact"]["artifact_id"],
                verification_id=v["artifact_id"], verification_hash=v["content_hash"],
                fixture_hash=vb["fixture_hash"], review_hash=r.content_hash,
                environment="staging", integration_id="orders",
                scope={"region": "us-east"}, confirmed=True)
    args.update(changes)
    return approve(tx, p["artifact_id"], **args)


def test_persisted_approval_is_deterministic_and_bound(evidence):
    tx, p, _, v = evidence
    a = call(tx, p, v)
    assert call(tx, p, v) == a
    assert load_final_approval(tx, a["artifact_id"]) == a
    body = json.loads(a["payload"])
    assert body["reviewer"] == "human:alice"
    assert body["target"]["integration_id"] == "orders"
    assert body["target"]["scope"] == {"region": "us-east"}


@pytest.mark.parametrize("changes", [
    {"confirmed": False}, {"confirmed": 1}, {"review_hash": "0" * 64},
    {"integration_id": "billing"}, {"environment": ""}, {"scope": {}},
])
def test_invalid_confirmation_evidence_or_target_fails_closed(evidence, changes):
    tx, p, _, v = evidence
    with pytest.raises(FinalApprovalError):
        call(tx, p, v, **changes)


def test_target_change_creates_distinct_evidence(evidence):
    tx, p, _, v = evidence
    a = call(tx, p, v)
    b = call(tx, p, v, environment="production")
    assert a["artifact_id"] != b["artifact_id"]
    assert a["content_hash"] != b["content_hash"]
