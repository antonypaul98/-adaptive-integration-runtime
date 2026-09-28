from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

import psycopg
import pytest

from air.change_evidence import EvidenceError, detect_and_persist
from air.dependency_impact import (Dependency, ImpactError, register_dependencies,
    load_registry, analyze_and_persist, load_impact)
from air.mapping_extraction import (MAPPING_VERSION, ExtractionError, extract_dependencies,
    register_adapter_mapping, load_adapter_mapping, extract_registered_dependencies, load_extraction)
from air.observer import ContractSnapshot
from air.postgres import canonical_json

pytestmark = pytest.mark.postgres


def document():
    return {'openapi': '3.1.0', 'info': {'title': 'Test', 'version': '1'}, 'paths': {
        '/items': {'parameters': [{'in': 'header', 'name': 'X-Client', 'schema': {'type': 'string'}}],
            'get': {'responses': {'200': {'content': {'application/json': {'schema': {
                'type': 'object', 'properties': {'id': {'type': 'string'}}}}}}}},
            'post': {'requestBody': {'content': {'application/json': {'schema': {
                'type': 'object', 'properties': {'name': {'type': 'string'}}}}}},
                'responses': {'204': {'description': 'ok'}}}}}}


def save_snapshot(tx, contract=None):
    value = canonical_json(document() if contract is None else contract)
    return ContractSnapshot(tx.tenant_id, 'mapping-test', 'https://example.com',
        datetime.now(timezone.utc).isoformat(), '8.8.8.8', 0, value,
        sha256(value.encode()).hexdigest()).persist(tx, uuid4().hex)


def manifest(tx, snapshot, adapter='billing'):
    return {'mapping_version': MAPPING_VERSION, 'tenant_id': str(tx.tenant_id),
        'snapshot_id': str(snapshot['artifact_id']), 'adapter_id': adapter, 'mappings': [
            {'mapping_id': 'fetch-items', 'method': 'GET', 'path': '/items', 'bindings': [
                {'binding_id': 'id', 'contract': {'kind': 'response_body', 'status': '200',
                    'media_type': 'application/json', 'field': '/id'},
                 'adapter_field': '/invoice/id', 'transform': 'identity'}]}]}


def create(tx):
    snapshot = save_snapshot(tx)
    mapping = register_adapter_mapping(tx, manifest(tx, snapshot))
    base = register_dependencies(tx, snapshot['artifact_id'],
        [Dependency('workflow', 'read', '/paths/~1items/get', 'GET /items', 'workflow')])
    result = extract_registered_dependencies(tx, [mapping['artifact_id']], explicit_registry_id=base['artifact_id'])
    return {'snapshot': snapshot, 'mapping': mapping, 'base': base, **result}


@pytest.fixture
def saved(database, repos):
    with repos[0].transaction(database['tenants'][0]) as tx:
        return create(tx)


def test_persistence_reload_idempotence_and_provenance(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        assert register_adapter_mapping(tx, manifest(tx, saved['snapshot'])) == saved['mapping']
        result = extract_registered_dependencies(tx, [saved['mapping']['artifact_id']] * 2,
            explicit_registry_id=saved['base']['artifact_id'])
        assert result['registry'] == saved['registry'] and result['extraction'] == saved['extraction']
        assert load_adapter_mapping(tx, saved['mapping']['artifact_id']) == saved['mapping']
        assert load_registry(tx, saved['registry']['artifact_id']) == saved['registry']
        assert load_extraction(tx, saved['extraction']['artifact_id']) == saved['extraction']
        payload = json.loads(saved['extraction']['payload'])
        assert payload['tenant_id'] == str(tx.tenant_id)
        assert payload['snapshot']['artifact_id'] == str(saved['snapshot']['artifact_id'])
        normalized = json.loads(saved['mapping']['payload'])['manifest']
        for row in payload['provenance']:
            assert row['mapping_artifact']['artifact_id'] == str(saved['mapping']['artifact_id'])
            assert row['mapping_artifact']['artifact_hash'] == saved['mapping']['content_hash']
            assert row['dependency']['integration_kind'] == 'adapter'
            for source in row['sources']:
                value = normalized
                for token in source['manifest_location'].split('/')[1:]:
                    value = value[int(token)] if isinstance(value, list) else value[token]
                assert value.get('binding_id') == 'id' or value.get('mapping_id') == 'fetch-items'
        for kind in ('mapping', 'extraction', 'registry'):
            assert len([a for a in tx.audit() if a['artifact_id'] == saved[kind]['artifact_id']]) == 1


def test_explicit_and_extracted_registrations_reuse_existing_registry(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        normalized = json.loads(saved['mapping']['payload'])['manifest']
        manual = register_dependencies(tx, saved['snapshot']['artifact_id'], extract_dependencies(normalized, tx.tenant_id).dependencies)
        result = extract_registered_dependencies(tx, [saved['mapping']['artifact_id']])
        assert result['registry'] == manual  # No second registry model or dependency shape.
        combined = json.loads(saved['registry']['payload'])['dependencies']
        assert {d['integration_id'] for d in combined} == {'billing', 'workflow'}
        assert len(combined) == 3


def test_multiple_adapters_operations_order_and_duplicates(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        value = manifest(tx, saved['snapshot'], 'crm')
        value['mappings'].append({'mapping_id': 'create', 'method': 'POST', 'path': '/items', 'bindings': [
            {'binding_id': 'name', 'contract': {'kind': 'request_body', 'media_type': 'application/json', 'field': '/name'},
             'adapter_field': '/name', 'transform': 'identity'},
            {'binding_id': 'client', 'contract': {'kind': 'parameter', 'in': 'header', 'name': 'X-CLIENT'},
             'adapter_field': '/client', 'transform': 'identity'}]})
        second = register_adapter_mapping(tx, value)
        ids = [saved['mapping']['artifact_id'], second['artifact_id']]
        first = extract_registered_dependencies(tx, ids)
        again = extract_registered_dependencies(tx, [ids[1], ids[0], ids[1]])
        assert first == again
        assert len(json.loads(first['registry']['payload'])['dependencies']) == 7
        assert load_extraction(tx, first['extraction']['artifact_id']) == first['extraction']


def test_extracted_registry_feeds_existing_change_impact_pipeline(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        changed = document()
        del changed['paths']['/items']['get']['responses']['200']['content']['application/json']['schema']['properties']['id']
        new = save_snapshot(tx, changed)
        changes = detect_and_persist(tx, saved['snapshot']['artifact_id'], new['artifact_id'])
        impact = analyze_and_persist(tx, changes['artifact_id'], saved['registry']['artifact_id'])
        assert load_impact(tx, impact['artifact_id']) == impact
        rows = json.loads(impact['payload'])['analysis']['impacts']
        assert any(r['dependency']['integration_id'] == 'billing' and
            r['dependency']['mapping_id'] == 'fetch-items' and r['change_type'] == 'PROPERTY_REMOVED' and
            r['classification'] == 'BREAKING' and r['match'] == 'LOCATION_OVERLAP' for r in rows)


def test_cross_tenant_registration_extraction_reads_and_base_fail_closed(database, repos, saved):
    with repos[1].transaction(database['tenants'][1]) as tx:
        other = create(tx)
        for identity, loader in [(saved['mapping']['artifact_id'], load_adapter_mapping),
                                  (saved['extraction']['artifact_id'], load_extraction)]:
            with pytest.raises(ExtractionError, match='not_found_or_not_authorized'):
                loader(tx, identity)
            assert tx._connection.execute('SELECT * FROM air.artifacts WHERE artifact_id=%s', (identity,)).fetchall() == []
        with pytest.raises(ImpactError, match='not_found_or_not_authorized'):
            load_registry(tx, saved['registry']['artifact_id'])
        for ids in ([saved['mapping']['artifact_id']], [other['mapping']['artifact_id'], saved['mapping']['artifact_id']]):
            with pytest.raises(ExtractionError, match='not_found_or_not_authorized'):
                extract_registered_dependencies(tx, ids)
        with pytest.raises(ImpactError, match='not_found_or_not_authorized'):
            extract_registered_dependencies(tx, [other['mapping']['artifact_id']], explicit_registry_id=saved['base']['artifact_id'])
        with pytest.raises(ExtractionError, match='not_found_or_not_authorized'):
            register_adapter_mapping(tx, json.loads(saved['mapping']['payload'])['manifest'])
        with pytest.raises(EvidenceError, match='not_found_or_not_authorized'):
            register_adapter_mapping(tx, manifest(tx, saved['snapshot']))


@pytest.mark.parametrize('mutation', ['missing_owner', 'unsupported', 'ambiguous', 'missing_field', 'missing_operation'])
def test_registration_fails_before_writing_invalid_mappings(database, repos, saved, mutation):
    with repos[0].transaction(database['tenants'][0]) as tx:
        value = manifest(tx, saved['snapshot'])
        if mutation == 'missing_owner': del value['tenant_id']
        elif mutation == 'unsupported': value['mappings'][0]['bindings'][0]['transform'] = 'dynamic'
        elif mutation == 'ambiguous':
            value['mappings'].append({**deepcopy(value['mappings'][0]), 'path': '/other'})
        elif mutation == 'missing_field': value['mappings'][0]['bindings'][0]['contract']['field'] = '/not-present'
        else: value['mappings'][0]['method'] = 'DELETE'
        before = tx._connection.execute('SELECT count(*) AS n FROM air.artifacts').fetchone()['n']
        with pytest.raises((ExtractionError, ImpactError)):
            register_adapter_mapping(tx, value)
        assert tx._connection.execute('SELECT count(*) AS n FROM air.artifacts').fetchone()['n'] == before


def test_reject_ambiguous_adapter_revisions_and_mismatched_snapshot(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        value = manifest(tx, saved['snapshot'])
        value['mappings'][0]['bindings'][0]['adapter_field'] = '/new-target'
        revision = register_adapter_mapping(tx, value)
        with pytest.raises(ExtractionError, match='ambiguous_adapter_revision'):
            extract_registered_dependencies(tx, [saved['mapping']['artifact_id'], revision['artifact_id']])
        other = create(tx)
        with pytest.raises(ExtractionError, match='mapping_snapshot_mismatch'):
            extract_registered_dependencies(tx, [saved['mapping']['artifact_id'], other['mapping']['artifact_id']])
        with pytest.raises(ExtractionError, match='mapping_registry_snapshot_mismatch'):
            extract_registered_dependencies(tx, [saved['mapping']['artifact_id']], explicit_registry_id=other['base']['artifact_id'])


@pytest.mark.parametrize('kind', ['mapping', 'extraction'])
@pytest.mark.parametrize('statement', ['UPDATE air.artifacts SET payload=payload WHERE artifact_id=%s',
    'DELETE FROM air.artifacts WHERE artifact_id=%s'])
def test_mapping_and_extraction_are_immutable(database, repos, saved, kind, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx._connection.execute(statement, (saved[kind]['artifact_id'],))


@pytest.mark.parametrize('link', ['snapshot', 'registry', 'mapping', 'explicit_registry', 'provenance'])
@pytest.mark.parametrize('mutation', ['foreign', 'hash', 'missing'])
def test_database_rejects_invalid_extraction_links(database, repos, saved, link, mutation):
    with repos[1].transaction(database['tenants'][1]) as tx:
        other = create(tx)
    payload = json.loads(saved['extraction']['payload'])
    if link == 'snapshot': reference, foreign = payload['snapshot'], other['snapshot']
    elif link == 'registry': reference, foreign = payload['registry'], other['registry']
    elif link == 'mapping': reference, foreign = payload['mappings'][0], other['mapping']
    elif link == 'explicit_registry': reference, foreign = payload['explicit_registry'], other['base']
    else: reference, foreign = payload['provenance'][0]['mapping_artifact'], other['mapping']
    if mutation == 'foreign':
        reference['artifact_id'] = str(foreign['artifact_id']); reference['artifact_hash'] = foreign['content_hash']
    elif mutation == 'hash': reference['artifact_hash'] = '0' * 64
    else: del reference['artifact_id']
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx.put('adapter_dependency_extraction', uuid4().hex, payload)


@pytest.mark.parametrize('mutation', ['tenant', 'manifest_owner', 'manifest_missing_owner', 'manifest_snapshot', 'snapshot_hash'])
def test_database_enforces_registered_mapping_ownership(database, repos, saved, mutation):
    payload = json.loads(saved['mapping']['payload'])
    if mutation == 'tenant': payload['tenant_id'] = str(database['tenants'][1])
    elif mutation == 'manifest_owner': payload['manifest']['tenant_id'] = str(database['tenants'][1])
    elif mutation == 'manifest_missing_owner': del payload['manifest']['tenant_id']
    elif mutation == 'manifest_snapshot': payload['manifest']['snapshot_id'] = str(uuid4())
    else: payload['snapshot']['artifact_hash'] = '0' * 64
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx.put('registered_adapter_mapping', uuid4().hex, payload)


@pytest.mark.parametrize('kind', ['mapping', 'extraction'])
def test_reload_recomputes_and_rejects_forged_evidence(database, repos, saved, kind):
    payload = json.loads(saved[kind]['payload'])
    if kind == 'mapping': payload['manifest']['mappings'][0]['bindings'][0]['transform'] = 'unknown'
    else: payload['provenance'][0]['sources'][0]['reason'] = 'invented reason'
    with repos[0].transaction(database['tenants'][0]) as tx:
        record = tx.put(saved[kind]['kind'], uuid4().hex, payload)
        with pytest.raises(ExtractionError):
            (load_adapter_mapping if kind == 'mapping' else load_extraction)(tx, record['artifact_id'])


def test_caught_failure_does_not_leave_orphan_registry_or_audit(database, repos, saved, monkeypatch):
    with repos[0].transaction(database['tenants'][0]) as tx:
        mapping = register_adapter_mapping(tx, manifest(tx, saved['snapshot'], 'new-adapter'))
        before = tx._connection.execute('SELECT count(*) AS n FROM air.artifacts').fetchone()['n']
        before_audit = len(tx.audit())
        original = tx.put
        def failed_put(kind, key, payload):
            if kind == 'adapter_dependency_extraction': raise RuntimeError('simulated failure')
            return original(kind, key, payload)
        monkeypatch.setattr(tx, 'put', failed_put)
        with pytest.raises(RuntimeError):
            extract_registered_dependencies(tx, [mapping['artifact_id']])
        assert tx._connection.execute('SELECT count(*) AS n FROM air.artifacts').fetchone()['n'] == before
        assert len(tx.audit()) == before_audit


def test_concurrent_extraction_is_idempotent(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        mapping = register_adapter_mapping(tx, manifest(tx, saved['snapshot'], 'concurrent'))
    def extract(_):
        with repos[0].transaction(database['tenants'][0]) as tx:
            return extract_registered_dependencies(tx, [mapping['artifact_id']])
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(extract, range(2)))
    assert first == second
