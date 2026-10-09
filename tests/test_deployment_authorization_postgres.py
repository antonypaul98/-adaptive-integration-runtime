"""Real PostgreSQL read-only and tenant-bound execution preflight checks."""
import pytest
from air.deployment_authorization import ExecutionBoundaryError
from test_deployment_authorization import check
from test_final_approval_postgres import approval_inputs, pg_call
from test_repair_evidence import reviewer
from test_sandbox_evaluation_postgres import approved
from test_replay_verification_postgres import sandbox

pytestmark = pytest.mark.postgres


def test_read_only_no_audit_change(database, reviewer, approval_inputs):
    tenant, proposal, verification = approval_inputs
    with reviewer.transaction(tenant) as tx:
        approval = pg_call(tx, proposal, verification)
        before = tx.audit()
        receipt = check(tx, proposal, verification, approval)
        assert receipt == check(tx, proposal, verification, approval)
        assert tx.audit() == before


def test_cross_tenant_approval_fails_closed(database, repos, reviewer, approval_inputs):
    tenant, proposal, verification = approval_inputs
    with reviewer.transaction(tenant) as tx:
        approval = pg_call(tx, proposal, verification)
    with repos[1].transaction(database["tenants"][1]) as tx:
        with pytest.raises(ExecutionBoundaryError):
            check(tx, proposal, verification, approval)
