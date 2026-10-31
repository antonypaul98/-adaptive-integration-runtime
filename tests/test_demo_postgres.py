"""PostgreSQL acceptance for the persisted AIR impact demonstration."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

import pytest

from air.change_evidence import EvidenceError
from air.demo import DemoError, persist_impact_demo
from air.dependency_impact import ImpactError
from air.observer import ContractSnapshot
from air.postgres import EvidenceTransaction, canonical_json

pytestmark = pytest.mark.postgres


def _contract(value_type="integer"):
    return {
        "openapi": "3.1.0",
        "info": {"title": "Persisted demo", "version": "1"},
        "paths": {
            "/items": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": value_type}
                                        },
                                    }
                                }
                            },
                        }
                    }
                }
            },
            "/ledger": {
                "get": {"responses": {"200": {"description": "OK"}}}
            },
        },
    }


def _snapshot(tx, contract, observed_at):
    value = canonical_json(contract)
    return ContractSnapshot(
        tx.tenant_id,
        "persisted-demo-fixture",
        "https://example.com",
        observed_at,
        "192.0.2.10",
        0,
        value,
        sha256(value.encode()).hexdigest(),
    ).persist(tx, uuid4().hex)


def _dependency(name, location, operation="GET /items"):
    return {
        "integration_id": name,
        "mapping_id": "item-id",
        "location": location,
        "operation": operation,
        "integration_kind": "adapter",
    }


def _registry(*, invalid_location=False):
    direct = _dependency(
        "private-client",
        (
            "/paths/~1missing/get"
            if invalid_location
            else "/paths/~1items/get/responses/200/content/"
            "application~1json/schema/properties/id"
        ),
    )
    downstream = _dependency(
        "private-worker",
        "/paths/~1ledger/get/responses/200",
        "GET /ledger",
    )
    return {
        "dependencies": [direct, downstream],
        "workflow_edges": [
            {
                "upstream": direct,
                "downstream": downstream,
                "relation": "consumes_output",
            }
        ],
    }


@pytest.fixture
def snapshots(database, repos):
    tenant = database["tenants"][0]
    with repos[0].transaction(tenant) as tx:
        previous = _snapshot(
            tx, _contract(), datetime(2026, 10, 31, tzinfo=timezone.utc).isoformat()
        )
        current = _snapshot(
            tx,
            _contract("string"),
            datetime(2026, 10, 31, 0, 1, tzinfo=timezone.utc).isoformat(),
        )
    return previous, current


def test_persisted_demo_is_idempotent_reloaded_redacted_and_audited(
    database, repos, snapshots
):
    tenant = database["tenants"][0]
    previous, current = snapshots
    with repos[0].transaction(tenant) as tx:
        first = persist_impact_demo(
            tx, previous["artifact_id"], current["artifact_id"], _registry()
        )
        second = persist_impact_demo(
            tx, previous["artifact_id"], current["artifact_id"], _registry()
        )
        assert second == first
        unsigned = {key: value for key, value in first.items() if key != "receipt_hash"}
        assert first["receipt_hash"] == sha256(
            canonical_json(unsigned).encode()
        ).hexdigest()
        assert first["summary"] == {
            "change_count": 1,
            "direct_impact_count": 1,
            "transitive_impact_count": 1,
            "recorded_review_node_count": 2,
            "redacted_visual_node_count": 2,
        }
        assert first["coverage"]["all_artifacts_reloaded_and_recomputed"] is True
        rendered = canonical_json(first)
        assert "private-client" not in rendered
        assert "private-worker" not in rendered
        assert "/paths/" not in rendered
        artifact_ids = {
            value["artifact_id"] for value in first["artifacts"].values()
        }
        assert len(
            [event for event in tx.audit() if str(event["artifact_id"]) in artifact_ids]
        ) == 5


def test_persisted_demo_rejects_cross_tenant_snapshots_without_writes(
    database, repos, snapshots
):
    previous, current = snapshots
    other = database["tenants"][1]
    with repos[1].transaction(other) as tx:
        before = tx._connection.execute(
            "SELECT count(*) FROM air.artifacts WHERE tenant_id=%s", (other,)
        ).fetchone()["count"]
        with pytest.raises(
            EvidenceError, match="snapshot_not_found_or_not_authorized"
        ):
            persist_impact_demo(
                tx, previous["artifact_id"], current["artifact_id"], _registry()
            )
        after = tx._connection.execute(
            "SELECT count(*) FROM air.artifacts WHERE tenant_id=%s", (other,)
        ).fetchone()["count"]
        assert after == before


def test_persisted_demo_failure_rolls_back_partial_chain(database, repos, snapshots):
    tenant = database["tenants"][0]
    previous, current = snapshots
    with repos[0].transaction(tenant) as tx:
        before = tx._connection.execute(
            "SELECT count(*) FROM air.artifacts WHERE tenant_id=%s", (tenant,)
        ).fetchone()["count"]
    with pytest.raises(ImpactError, match="dependency_operation_not_found"):
        with repos[0].transaction(tenant) as tx:
            persist_impact_demo(
                tx,
                previous["artifact_id"],
                current["artifact_id"],
                _registry(invalid_location=True),
            )
    with repos[0].transaction(tenant) as tx:
        after = tx._connection.execute(
            "SELECT count(*) FROM air.artifacts WHERE tenant_id=%s", (tenant,)
        ).fetchone()["count"]
    assert after == before


def test_persisted_demo_rejects_non_transaction_and_invalid_registry():
    with pytest.raises(DemoError, match="invalid_evidence_transaction"):
        persist_impact_demo(None, "previous", "current", _registry())
    with pytest.raises(DemoError, match="invalid_registry_shape"):
        persist_impact_demo(
            EvidenceTransaction.__new__(EvidenceTransaction),
            "previous",
            "current",
            {},
        )
