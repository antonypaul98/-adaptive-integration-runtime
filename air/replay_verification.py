"""Bounded declarative state-projection replay; never executes adapter code.

Each fixture selects an object-key path from the approved proposed state and
compares its canonical JSON with an expected value. PASS is evidence only, not
deployment permission. Unsupported operations fail closed without persistence.
"""
import json
import math
import re
from hashlib import sha256

from .postgres import canonical_json
from .repair_proposal import authorization, load_proposal, reference
from .sandbox_evaluation import load_evaluation

VERSION = "air-replay-verification-v1"
MAX_BYTES = 65536
MAX_CASES = 32
MAX_NODES = 4096
MAX_DEPTH = 16


class ReplayError(ValueError):
    pass


def _encoded(value):
    # Bound traversal before encoding, including cycles and excessive nesting.
    stack = [(value, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise ReplayError("replay_bounds_exceeded")
        if type(item) is dict:
            if len(item) > MAX_NODES or any(type(k) is not str for k in item):
                raise ReplayError("invalid_json")
            stack.extend((v, depth + 1) for v in item.values())
        elif type(item) is list:
            if len(item) > MAX_NODES:
                raise ReplayError("replay_bounds_exceeded")
            stack.extend((v, depth + 1) for v in item)
        elif item is None or type(item) in (str, bool, int):
            if type(item) is str and len(item) > MAX_BYTES:
                raise ReplayError("replay_bounds_exceeded")
        elif type(item) is float and math.isfinite(item):
            pass
        else:
            raise ReplayError("invalid_json")
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_BYTES:
            raise ReplayError("replay_bounds_exceeded")
    except (ValueError, UnicodeError) as exc:
        raise ReplayError("invalid_or_oversized_json") from exc
    return encoded


def digest(value):
    return sha256(_encoded(value).encode("utf-8")).hexdigest()


def normalize_fixture(fixture):
    fixture = json.loads(_encoded(fixture))
    if (type(fixture) is not dict or set(fixture) != {"version", "cases"}
            or fixture["version"] != VERSION or type(fixture["cases"]) is not list
            or not 1 <= len(fixture["cases"]) <= MAX_CASES):
        raise ReplayError("unsupported_fixture")
    seen = set()
    for case in fixture["cases"]:
        if type(case) is not dict or set(case) != {"case_id", "input", "expected"}:
            raise ReplayError("invalid_case")
        identity = case["case_id"]
        if (type(identity) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", identity)
                or identity in seen):
            raise ReplayError("invalid_or_duplicate_case_id")
        seen.add(identity)
        inp = case["input"]
        if type(inp) is not dict or set(inp) != {"path"}:
            raise ReplayError("unsupported_input")
        path = inp["path"]
        if (type(path) is not list or not 1 <= len(path) <= MAX_DEPTH
                or any(type(k) is not str or not 1 <= len(k) <= 128 for k in path)):
            raise ReplayError("unsupported_path")
    fixture["cases"].sort(key=lambda c: c["case_id"])
    return fixture


def compare(state, fixture):
    state = json.loads(_encoded(state))
    fixture = normalize_fixture(fixture)
    results = []
    for case in fixture["cases"]:
        actual = state
        for key in case["input"]["path"]:
            if type(actual) is not dict or key not in actual:
                raise ReplayError("unsupported_or_missing_path")
            actual = actual[key]
        actual_hash, expected_hash = digest(actual), digest(case["expected"])
        results.append({"case_id": case["case_id"], "actual_hash": actual_hash,
                        "expected_hash": expected_hash, "matches": actual_hash == expected_hash})
    return {"status": "PASS" if all(c["matches"] for c in results) else "FAIL", "cases": results}


def _payload(tx, proposal, sandbox, fixture):
    p, s = json.loads(proposal["payload"]), json.loads(sandbox["payload"])
    if (s["proposal"] != reference(proposal) or s["revision"] != p["revision"]
            or s["impact"] != p["impact"] or s["change_evidence"] != p["change_evidence"]
            or s["result"]["state_hash"] != digest(p["description"]["proposed_state"])):
        raise ReplayError("sandbox_binding_mismatch")
    normalized = normalize_fixture(fixture)
    return {"tenant_id": str(tx.tenant_id), "replay_version": VERSION,
            "proposal": reference(proposal), "revision": p["revision"],
            "sandbox": reference(sandbox), "impact": p["impact"],
            "change_evidence": p["change_evidence"], "fixture": normalized,
            "fixture_hash": digest(normalized),
            "result": compare(p["description"]["proposed_state"], normalized)}


def replay(tx, proposal_id, *, proposal_hash, revision, current_impact_id,
           sandbox_id, sandbox_hash, fixture):
    """Recheck live exact approval and persist immutable, tenant-bound evidence."""
    authorization(tx, proposal_id, proposal_hash=proposal_hash, revision=revision,
                  current_impact_id=current_impact_id)
    proposal, sandbox = load_proposal(tx, proposal_id), load_evaluation(tx, sandbox_id)
    if sandbox["content_hash"] != sandbox_hash:
        raise ReplayError("sandbox_binding_mismatch")
    payload = _payload(tx, proposal, sandbox, fixture)
    # Whole evidence may exceed the per-fixture limit, but the repository caps it.
    key = sha256(canonical_json(payload).encode()).hexdigest()
    return tx.put("replay_verification", key, payload)


def load_verification(tx, identity):
    """Verify historical evidence; this does not grant fresh authorization."""
    try:
        record = tx.get_by_id(identity, kind="replay_verification")
    except (TypeError, ValueError):
        record = None
    if record is None or record["tenant_id"] != tx.tenant_id:
        raise ReplayError("not_found_or_not_authorized")
    try:
        p = json.loads(record["payload"])
        proposal = load_proposal(tx, p["proposal"]["artifact_id"])
        sandbox = load_evaluation(tx, p["sandbox"]["artifact_id"])
        expected = canonical_json(_payload(tx, proposal, sandbox, p["fixture"]))
        hashed = sha256(expected.encode()).hexdigest()
        if (expected != record["payload"] or hashed != record["content_hash"]
                or hashed != record["idempotency_key"]):
            raise ReplayError("invalid_verification")
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayError("invalid_verification") from exc
    return record
