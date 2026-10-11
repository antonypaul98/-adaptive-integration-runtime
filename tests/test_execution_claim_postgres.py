"""Real PostgreSQL single-use pre-execution claim checks."""
import pytest

from air.execution_claim import (
    ExecutionClaimError,
    claim_execution,
    load_execution_claim,
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


def save_claim(tx, plan, **overrides):
    args = {
        "plan_hash": plan.content_hash,
        "observed_target_state_hash": "2" * 64,
        "executor_identity_hash": "7" * 64,
        "claim_nonce_hash": "8" * 64,
    }
    args.update(overrides)
    return claim_execution(tx, plan, **args)


def test_exactly_one_claim_audit_entry_and_conflict_fails(
        database, reviewer, approval_inputs):
    tenant, proposal, verification = approval_inputs
    with reviewer.transaction(tenant) as tx:
        approval = pg_call(tx, proposal, verification)
        plan = make_plan(tx, proposal, verification, approval)
        before = tx.audit()
        claim = save_claim(tx, plan)
        assert save_claim(tx, plan) == claim
        assert len(tx.audit()) == len(before) + 1
        assert load_execution_claim(tx, claim["artifact_id"]) == claim
        with pytest.raises(ExecutionClaimError, match="plan_already_claimed"):
            save_claim(tx, plan, executor_identity_hash="9" * 64)


def test_cross_tenant_claim_read_and_write_fail_closed(
        database, repos, reviewer, approval_inputs):
    tenant, proposal, verification = approval_inputs
    with reviewer.transaction(tenant) as tx:
        approval = pg_call(tx, proposal, verification)
        plan = make_plan(tx, proposal, verification, approval)
        claim = save_claim(tx, plan)
    with repos[1].transaction(database["tenants"][1]) as tx:
        with pytest.raises(ExecutionClaimError):
            save_claim(tx, plan)
        with pytest.raises(ExecutionClaimError):
            load_execution_claim(tx, claim["artifact_id"])
