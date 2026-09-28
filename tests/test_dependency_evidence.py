from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

import psycopg
import pytest

from air.change_evidence import EvidenceError, detect_and_persist
from air.dependency_impact import (Dependency, ImpactError, register_dependencies,
    load_registry, analyze_and_persist, load_impact)
from air.observer import ContractSnapshot
from air.postgres import canonical_json

pytestmark = pytest.mark.postgres


def snapshot(tx, removed=False):
    contract = {'openapi': '3.1.0', 'info': {'title': 'Demo', 'version': '1'},
        'paths': {} if removed else {'/items': {'get': {'responses': {'200': {'description': 'OK'}}}}}}
    value = canonical_json(contract)
    return ContractSnapshot(tx.tenant_id, 'impact-source', 'https://example.com',
        datetime.now(timezone.utc).isoformat(), '8.8.8.8', 0, value,
        sha256(value.encode()).hexdigest()).persist(tx, uuid4().hex)


def dependency():
    return Dependency('billing', 'fetch-items', '/paths/~1items/get', 'GET /items', 'workflow')


@pytest.fixture
def evidence(database, repos):
    with repos[0].transaction(database['tenants'][0]) as tx:
        old, new = snapshot(tx), snapshot(tx, True)
        changes = detect_and_persist(tx, old['artifact_id'], new['artifact_id'])
        registry = register_dependencies(tx, old['artifact_id'], [dependency()])
        impact = analyze_and_persist(tx, changes['artifact_id'], registry['artifact_id'])
        return {'old': old, 'new': new, 'changes': changes, 'registry': registry, 'impact': impact}


def test_registry_impact_persistence_reload_idempotence_audit(database, repos, evidence):
    with repos[0].transaction(database['tenants'][0]) as tx:
        assert register_dependencies(tx, evidence['old']['artifact_id'], [dependency(), dependency()]) == evidence['registry']
        assert analyze_and_persist(tx, evidence['changes']['artifact_id'], evidence['registry']['artifact_id']) == evidence['impact']
        assert load_registry(tx, evidence['registry']['artifact_id']) == evidence['registry']
        assert load_impact(tx, evidence['impact']['artifact_id']) == evidence['impact']
        payload = json.loads(evidence['impact']['payload'])
        assert payload['tenant_id'] == str(tx.tenant_id)
        assert payload['analysis']['impacts'][0]['dependency']['mapping_id'] == 'fetch-items'
        assert payload['change_evidence']['artifact_hash'] == evidence['changes']['content_hash']
        assert payload['registry']['artifact_hash'] == evidence['registry']['content_hash']
        for kind in ('registry', 'impact'):
            assert len([a for a in tx.audit() if a['artifact_id'] == evidence[kind]['artifact_id']]) == 1


def test_other_tenant_cannot_read_register_or_analyze(database, repos, evidence):
    with repos[1].transaction(database['tenants'][1]) as tx:
        for kind, loader in [('registry', load_registry), ('impact', load_impact)]:
            with pytest.raises(ImpactError, match='not_found_or_not_authorized'):
                loader(tx, evidence[kind]['artifact_id'])
            assert tx._connection.execute('SELECT * FROM air.artifacts WHERE artifact_id=%s', (evidence[kind]['artifact_id'],)).fetchall() == []
        with pytest.raises(EvidenceError, match='not_found_or_not_authorized'):
            register_dependencies(tx, evidence['old']['artifact_id'], [dependency()])
        with pytest.raises(EvidenceError, match='not_found_or_not_authorized'):
            analyze_and_persist(tx, evidence['changes']['artifact_id'], evidence['registry']['artifact_id'])
        own_old, own_new = snapshot(tx), snapshot(tx, True)
        own_changes = detect_and_persist(tx, own_old['artifact_id'], own_new['artifact_id'])
        with pytest.raises(ImpactError, match='not_found_or_not_authorized'):
            analyze_and_persist(tx, own_changes['artifact_id'], evidence['registry']['artifact_id'])


@pytest.mark.parametrize('kind', ['registry', 'impact'])
@pytest.mark.parametrize('statement', ['UPDATE air.artifacts SET payload=payload WHERE artifact_id=%s',
    'DELETE FROM air.artifacts WHERE artifact_id=%s'])
def test_dependency_evidence_is_immutable(database, repos, evidence, kind, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx._connection.execute(statement, (evidence[kind]['artifact_id'],))


@pytest.mark.parametrize('kind,field', [('registry', 'snapshot'), ('impact', 'registry'), ('impact', 'change_evidence')])
@pytest.mark.parametrize('mutation', ['foreign_id', 'hash', 'missing', 'bad_uuid'])
def test_database_link_enforcement(database, repos, evidence, kind, field, mutation):
    payload = json.loads(evidence[kind]['payload'])
    if mutation == 'foreign_id':
        with repos[1].transaction(database['tenants'][1]) as tx:
            old, new = snapshot(tx), snapshot(tx, True)
            other_registry = register_dependencies(tx, old['artifact_id'], [dependency()])
            other_change = detect_and_persist(tx, old['artifact_id'], new['artifact_id'])
            other = {'snapshot': old, 'registry': other_registry, 'change_evidence': other_change}[field]
        payload[field]['artifact_id'] = str(other['artifact_id'])
        payload[field]['artifact_hash'] = other['content_hash']
    elif mutation == 'hash':
        payload[field]['artifact_hash'] = '0' * 64
    elif mutation == 'missing':
        del payload[field]
    else:
        payload[field]['artifact_id'] = 'invalid'
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx.put(evidence[kind]['kind'], uuid4().hex, payload)


def test_wrong_snapshot_registry_rejected_in_application_and_database(database, repos, evidence):
    with repos[0].transaction(database['tenants'][0]) as tx:
        other = snapshot(tx)
        registry = register_dependencies(tx, other['artifact_id'], [dependency()])
        with pytest.raises(ImpactError, match='snapshot_mismatch'):
            analyze_and_persist(tx, evidence['changes']['artifact_id'], registry['artifact_id'])
    payload = json.loads(evidence['impact']['payload'])
    payload['registry'] = {'artifact_id': str(registry['artifact_id']), 'artifact_hash': registry['content_hash']}
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx.put('contract_dependency_impact', uuid4().hex, payload)


def test_failed_registration_rolls_back_transaction(database, repos, evidence):
    key = uuid4().hex
    with pytest.raises(ImpactError, match='location_not_found'):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx.put('test', key, {})
            register_dependencies(tx, evidence['old']['artifact_id'], [Dependency('a', 'b', '/missing')])
    with repos[0].transaction(database['tenants'][0]) as tx:
        assert tx.get('test', key) is None


def test_forged_impact_rejected_on_reload(database, repos, evidence):
    payload = json.loads(evidence['impact']['payload'])
    payload['analysis']['impacts'] = []
    with repos[0].transaction(database['tenants'][0]) as tx:
        forged = tx.put('contract_dependency_impact', uuid4().hex, payload)
        with pytest.raises(ImpactError, match='integrity_failure'):
            load_impact(tx, forged['artifact_id'])


def test_concurrent_impact_detection_returns_one_artifact(database, repos, evidence):
    from concurrent.futures import ThreadPoolExecutor
    # Use a fresh registry revision so neither invocation has an existing impact.
    with repos[0].transaction(database['tenants'][0]) as tx:
        registry = register_dependencies(tx, evidence['old']['artifact_id'],
            [Dependency('second', 'mapping', '/paths/~1items/get', 'GET /items')])
    def detect(_):
        with repos[0].transaction(database['tenants'][0]) as tx:
            return analyze_and_persist(tx, evidence['changes']['artifact_id'], registry['artifact_id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(detect, range(2)))
    assert first == second


@pytest.mark.parametrize('kind', ['registry', 'impact'])
def test_database_rejects_forged_payload_tenant(database, repos, evidence, kind):
    payload = json.loads(evidence[kind]['payload'])
    payload['tenant_id'] = str(database['tenants'][1])
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx.put(evidence[kind]['kind'], uuid4().hex, payload)
