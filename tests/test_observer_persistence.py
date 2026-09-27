from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from air.observer import ContractSnapshot, ObservationError
from air.postgres import IdempotencyConflict

pytestmark = pytest.mark.postgres


def snapshot(tenant):
    return ContractSnapshot(tenant, 'source', 'https://example.com',
        datetime.now(timezone.utc).isoformat(), '8.8.8.8', 0,
        '{"type":"object"}', sha256(b'{"type":"object"}').hexdigest())


def test_snapshot_is_persistent_idempotent_and_tenant_isolated(database, repos):
    tenant, other = database['tenants']
    item, key = snapshot(tenant), uuid4().hex
    with repos[0].transaction(tenant) as tx:
        first = item.persist(tx, key)
        assert item.persist(tx, key) == first
    with repos[1].transaction(other) as tx:
        assert tx.get('contract_observation', key) is None
        assert all(e['artifact_id'] != first['artifact_id'] for e in tx.audit())
        with pytest.raises(ObservationError, match='tenant_mismatch'):
            item.persist(tx, key)
    with repos[0].transaction(tenant) as tx:
        assert tx.get('contract_observation', key) == first


def test_snapshot_conflict_preserves_original(database, repos):
    tenant, key = database['tenants'][0], uuid4().hex
    with repos[0].transaction(tenant) as tx:
        original = snapshot(tenant).persist(tx, key)
    with pytest.raises(IdempotencyConflict):
        with repos[0].transaction(tenant) as tx:
            snapshot(tenant).persist(tx, key)
    with repos[0].transaction(tenant) as tx:
        assert tx.get('contract_observation', key) == original
