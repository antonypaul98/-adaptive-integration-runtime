"""Real PostgreSQL append-only, tenant-bound single-use outcome checks."""
import pytest

from air.execution_claim import claim_execution
from air.execution_outcome import (
    ExecutionOutcomeError,
    load_execution_outcome,
    record_execution_outcome,
)
from air.execution_plan import prepare_execution_plan
from test_deployment_authorization import check
from test_final_approval_postgres import approval_inputs, pg_call
from test_repair_evidence import reviewer
from test_sandbox_evaluation_postgres import approved
from test_replay_verification_postgres import sandbox
from test_workflow_evidence import saved

pytestmark = pytest.mark.postgres


def make_plan(tx, proposal, verification, approval):
    boundary = check(tx, proposal, verification, approval)
    return prepare_execution_plan(
        boundary, boundary_hash=boundary.content_hash,
        target_state_hash="2" * 64)


def save_claim(tx, plan):
    return claim_execution(
        tx, plan, plan_hash=plan.content_hash,
        observed_target_state_hash="2" * 64,
        executor_identity_hash="8" * 64,
        claim_nonce_hash="9" * 64)


def save(tx, plan, claim, **overrides):
    args = {
        "claim_id": claim["artifact_id"],
        "plan_hash": plan.content_hash,
        "observed_target_state_hash": "2" * 64,
        "status": "succeeded",
        "outcome_hash": "7" * 64,
        "reason_code": "verified_completion",
    }
    args.update(overrides)
    return record_execution_outcome(tx, plan, **args)


def test_single_audit_entry_and_conflicting_reuse_fails(
        database, reviewer, approval_inputs):
    tenant, proposal, verification = approval_inputs
    with reviewer.transaction(tenant) as tx:
        approval = pg_call(tx, proposal, verification)
        plan = make_plan(tx, proposal, verification, approval)
        claim = save_claim(tx, plan)
        before = tx.audit()
        outcome = save(tx, plan, claim)
        assert save(tx, plan, claim) == outcome
        assert len(tx.audit()) == len(before) + 1
        assert load_execution_outcome(tx, outcome["artifact_id"]) == outcome
        with pytest.raises(ExecutionOutcomeError, match="plan_already_consumed"):
            save(tx, plan, claim, status="failed", outcome_hash="8" * 64,
                 reason_code="executor_failure")


def test_cross_tenant_outcome_read_and_write_fail_closed(
        database, repos, reviewer, approval_inputs):
    tenant, proposal, verification = approval_inputs
    with reviewer.transaction(tenant) as tx:
        approval = pg_call(tx, proposal, verification)
        plan = make_plan(tx, proposal, verification, approval)
        claim = save_claim(tx, plan)
        outcome = save(tx, plan, claim)
    with repos[1].transaction(database["tenants"][1]) as tx:
        with pytest.raises(ExecutionOutcomeError):
            save(tx, plan, claim)
        with pytest.raises(ExecutionOutcomeError):
            load_execution_outcome(tx, outcome["artifact_id"])
