"""Read-only deployment handoff plan. This module cannot execute deployments.

The plan binds a freshly revalidated execution-boundary receipt to an exact
caller-observed target-state hash. It deliberately contains no command, URL,
credential, callback, transport, or mutable execution state. A future executor
must independently re-read the target, reproduce ``target_state_hash``, consume
the plan once, and record append-only outcome evidence before taking any action.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from .deployment_authorization import (
    ExecutionBoundary,
    PURPOSE as BOUNDARY_PURPOSE,
    VERSION as BOUNDARY_VERSION,
)
from .postgres import canonical_json

VERSION = "air-execution-plan-v1"
PURPOSE = "READ_ONLY_EXECUTION_PLAN_NO_DEPLOYMENT_EXECUTION"
OPERATION = "activate_approved_mapping_revision"
_HASH = re.compile(r"[0-9a-f]{64}")


class ExecutionPlanError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionPlan:
    """Immutable non-authoritative handoff data, never a bearer credential."""

    payload: str

    @property
    def content_hash(self):
        return sha256(self.payload.encode("utf-8")).hexdigest()


def _hash(value, name):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ExecutionPlanError("invalid_" + name)
    return value


def prepare_execution_plan(boundary, *, boundary_hash, target_state_hash):
    """Bind exact authorization and observed target state without executing.

    ``target_state_hash`` must be derived from an authoritative, canonical read
    of the target immediately before this call. This function cannot discover
    or mutate external state and the result must not be treated as permission.
    """
    try:
        if not isinstance(boundary, ExecutionBoundary):
            raise ExecutionPlanError("invalid_boundary")
        boundary_hash = _hash(boundary_hash, "boundary_hash")
        target_state_hash = _hash(target_state_hash, "target_state_hash")
        if boundary.content_hash != boundary_hash:
            raise ExecutionPlanError("boundary_hash_mismatch")
        source = json.loads(boundary.payload)
        if (not isinstance(source, dict)
                or source.get("version") != BOUNDARY_VERSION
                or source.get("purpose") != BOUNDARY_PURPOSE
                or source.get("tenant_id") in (None, "")
                or type(source.get("revision")) is not int
                or source["revision"] < 1):
            raise ExecutionPlanError("invalid_boundary")
        for name in ("approval", "proposal", "verification", "target"):
            if not isinstance(source.get(name), dict) or not source[name]:
                raise ExecutionPlanError("invalid_boundary")
        if not isinstance(source["target"].get("scope"), dict):
            raise ExecutionPlanError("invalid_boundary")
        receipt = {
            "version": VERSION,
            "purpose": PURPOSE,
            "operation": OPERATION,
            "tenant_id": source["tenant_id"],
            "boundary_hash": boundary_hash,
            "target_state_hash": target_state_hash,
            "approval": source["approval"],
            "proposal": source["proposal"],
            "revision": source["revision"],
            "verification": source["verification"],
            "review_hash": source.get("review_hash"),
            "target": source["target"],
            "executor_requirements": {
                "revalidate_boundary": True,
                "revalidate_target_state_hash": True,
                "single_use": True,
                "append_only_outcome_evidence": True,
            },
        }
        return ExecutionPlan(canonical_json(receipt))
    except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError) as exc:
        if isinstance(exc, ExecutionPlanError):
            raise
        raise ExecutionPlanError("execution_plan_rejected") from exc
