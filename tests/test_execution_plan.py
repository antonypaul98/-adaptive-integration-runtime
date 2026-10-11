"""Capability-isolated read-only execution-plan tests."""
import json
from dataclasses import FrozenInstanceError

import pytest

from air.deployment_authorization import ExecutionBoundary
from air.execution_plan import (
    ExecutionPlanError,
    OPERATION,
    PURPOSE,
    prepare_execution_plan,
)
from air.postgres import canonical_json


def boundary():
    return ExecutionBoundary(canonical_json({
        "version": "air-execution-boundary-v1",
        "purpose": "READ_ONLY_PREFLIGHT_NO_DEPLOYMENT_EXECUTION",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "approval": {"artifact_id": "approval", "artifact_hash": "1" * 64},
        "proposal": {"artifact_id": "proposal", "artifact_hash": "2" * 64},
        "revision": 7,
        "verification": {"artifact_id": "verification", "artifact_hash": "3" * 64},
        "review_hash": "4" * 64,
        "target": {
            "environment": "staging",
            "integration_id": "orders",
            "mapping_id": "orders-v7",
            "scope": {"region": "us-east-1"},
        },
    }))


def test_plan_is_deterministic_immutable_and_non_executable():
    source = boundary()
    args = {"boundary_hash": source.content_hash, "target_state_hash": "5" * 64}
    plan = prepare_execution_plan(source, **args)
    assert plan == prepare_execution_plan(source, **args)
    payload = json.loads(plan.payload)
    assert payload["purpose"] == PURPOSE
    assert payload["operation"] == OPERATION
    assert payload["executor_requirements"] == {
        "append_only_outcome_evidence": True,
        "revalidate_boundary": True,
        "revalidate_target_state_hash": True,
        "single_use": True,
    }
    assert not ({"command", "url", "credential", "token", "secret"} & payload.keys())
    with pytest.raises(FrozenInstanceError):
        plan.payload = "changed"


@pytest.mark.parametrize("overrides", [
    {"boundary_hash": "0" * 64},
    {"target_state_hash": "not-a-hash"},
    {"boundary_hash": True},
])
def test_exact_hash_binding_fails_closed(overrides):
    source = boundary()
    args = {"boundary_hash": source.content_hash, "target_state_hash": "5" * 64}
    args.update(overrides)
    with pytest.raises(ExecutionPlanError):
        prepare_execution_plan(source, **args)


@pytest.mark.parametrize("source", [
    object(),
    ExecutionBoundary("not json"),
    ExecutionBoundary(canonical_json({
        "version": "wrong", "purpose": "wrong", "tenant_id": "tenant",
        "approval": {"id": "a"}, "proposal": {"id": "p"},
        "revision": 1, "verification": {"id": "v"}, "target": {"scope": {}},
    })),
])
def test_malformed_or_substituted_boundary_fails_closed(source):
    expected = source.content_hash if isinstance(source, ExecutionBoundary) else "0" * 64
    with pytest.raises(ExecutionPlanError):
        prepare_execution_plan(
            source, boundary_hash=expected, target_state_hash="5" * 64)
