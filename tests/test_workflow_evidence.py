from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from air.change_evidence import detect_and_persist
from air.dependency_impact import (Dependency, WorkflowEdge, ImpactError, register_dependencies,
    load_registry, analyze_and_persist, load_impact, WORKFLOW_VERSION)
from air.mapping_extraction import (MAPPING_VERSION, register_adapter_mapping,
    extract_registered_dependencies, load_extraction)
from air.observer import ContractSnapshot
from air.postgres import canonical_json
from test_workflow_impact import contract, dependencies

pytestmark = pytest.mark.postgres


def snapshot(tx, value):
    serialized = canonical_json(value)
    return ContractSnapshot(tx.tenant_id, 'workflow', 'https://example.com',
        datetime.now(timezone.utc).isoformat(), '8.8.8.8', 0, serialized,
        sha256(serialized.encode()).hexdigest()).persist(tx, uuid4().hex)


def graph(deps):
    return [WorkflowEdge(deps[a], deps[b]) for a,b in [(0,1),(1,2),(2,3),(3,1),(0,4),(4,3)]]


def setup(tx):
    old = contract(); new = deepcopy(old); del new['paths']['/node0']
    previous, current = snapshot(tx, old), snapshot(tx, new)
    changes = detect_and_persist(tx, previous['artifact_id'], current['artifact_id'])
    return previous, changes


@pytest.fixture
def saved(database, repos):
    with repos[0].transaction(database['tenants'][0]) as tx:
        previous, changes = setup(tx)
        deps = dependencies()
        registry = register_dependencies(tx, previous['artifact_id'], deps, workflow_edges=graph(deps))
        impact = analyze_and_persist(tx, changes['artifact_id'], registry['artifact_id'])
        return {'snapshot': previous, 'changes': changes, 'registry': registry, 'impact': impact}


def test_workflow_persistence_reload_idempotence_and_audit(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        deps = dependencies()
        assert register_dependencies(tx, saved['snapshot']['artifact_id'], reversed(deps),
            workflow_edges=list(reversed(graph(deps))) + [graph(deps)[0]]) == saved['registry']
        assert load_registry(tx, saved['registry']['artifact_id']) == saved['registry']
        assert analyze_and_persist(tx, saved['changes']['artifact_id'], saved['registry']['artifact_id']) == saved['impact']
        assert load_impact(tx, saved['impact']['artifact_id']) == saved['impact']
        payload = json.loads(saved['impact']['payload'])
        assert payload['tenant_id'] == str(tx.tenant_id)
        assert payload['impact_version'] == WORKFLOW_VERSION
        assert len(payload['analysis']['downstream_impacts']) == 4
        assert payload['registry']['artifact_hash'] == saved['registry']['content_hash']
        assert payload['change_evidence']['artifact_hash'] == saved['changes']['content_hash']
        registered_edges = json.loads(saved['registry']['payload'])['workflow_edges']
        for result in payload['analysis']['downstream_impacts']:
            for hop in result['path']['edges']:
                assert {k: hop[k] for k in ('upstream', 'downstream', 'relation')} in registered_edges
        for kind in ('registry', 'impact'):
            assert len([a for a in tx.audit() if a['artifact_id'] == saved[kind]['artifact_id']]) == 1


def test_v1_registry_and_impact_remain_compatible(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        registry = register_dependencies(tx, saved['snapshot']['artifact_id'], dependencies())
        impact = analyze_and_persist(tx, saved['changes']['artifact_id'], registry['artifact_id'])
        assert json.loads(registry['payload'])['registry_version'] == 'air-dependency-impact-v1'
        assert 'workflow_edges' not in json.loads(registry['payload'])
        assert 'downstream_impacts' not in json.loads(impact['payload'])['analysis']
        assert load_registry(tx, registry['artifact_id']) == registry
        assert load_impact(tx, impact['artifact_id']) == impact


@pytest.mark.parametrize('mode', ['explicit', 'extracted_seed', 'mixed_base'])
def test_explicit_extracted_and_mixed_registrations_feed_transitive_impact(database, repos, saved, mode):
    with repos[0].transaction(database['tenants'][0]) as tx:
        deps = dependencies()
        if mode == 'explicit':
            registry = saved['registry']
        else:
            manifest = {'mapping_version': MAPPING_VERSION, 'tenant_id': str(tx.tenant_id),
                'snapshot_id': str(saved['snapshot']['artifact_id']), 'adapter_id': 'node0',
                'mappings': [{'mapping_id': 'read', 'method': 'GET', 'path': '/node0', 'bindings': []}]}
            mapping = register_adapter_mapping(tx, manifest)
            extracted = extract_registered_dependencies(tx, [mapping['artifact_id']],
                explicit_registry_id=saved['registry']['artifact_id'] if mode == 'mixed_base' else None)
            assert load_extraction(tx, extracted['extraction']['artifact_id']) == extracted['extraction']
            if mode == 'mixed_base':
                registry = extracted['registry']
                assert registry == saved['registry']  # Existing edges preserved, never silently dropped.
            else:
                extracted_nodes = [Dependency(**d) for d in json.loads(extracted['registry']['payload'])['dependencies']]
                assert extracted_nodes == deps[:1]
                registered = extracted_nodes + deps[1:]
                registry = register_dependencies(tx, saved['snapshot']['artifact_id'], registered,
                                                 workflow_edges=graph(registered))
        impact = analyze_and_persist(tx, saved['changes']['artifact_id'], registry['artifact_id'])
        assert impact == saved['impact']
        assert {r['dependency']['integration_id'] for r in json.loads(impact['payload'])['analysis']['downstream_impacts']} == {'node1','node2','node3','node4'}


def test_cross_tenant_registry_impact_and_traversal_fail_closed(database, repos, saved):
    with repos[1].transaction(database['tenants'][1]) as tx:
        for artifact, loader in [(saved['registry'], load_registry), (saved['impact'], load_impact)]:
            with pytest.raises(ImpactError, match='not_found_or_not_authorized'):
                loader(tx, artifact['artifact_id'])
            assert tx._connection.execute('SELECT * FROM air.artifacts WHERE artifact_id=%s', (artifact['artifact_id'],)).fetchall() == []
        own_snapshot, own_changes = setup(tx)
        with pytest.raises(ImpactError, match='not_found_or_not_authorized'):
            analyze_and_persist(tx, own_changes['artifact_id'], saved['registry']['artifact_id'])
        own = [replace(d, integration_id='own-' + d.integration_id) for d in dependencies()]
        with pytest.raises(ImpactError, match='endpoint_not_registered'):
            register_dependencies(tx, own_snapshot['artifact_id'], own,
                workflow_edges=[WorkflowEdge(own[0], dependencies()[1])])


@pytest.mark.parametrize('mutation', ['missing', 'null', 'malformed', 'unregistered', 'foreign_tenant',
    'external_registry', 'unknown_relation', 'v1_edges', 'empty_edges', 'wrong_shape', 'extra_endpoint_key'])
def test_database_rejects_invalid_or_foreign_workflow_edges(database, repos, saved, mutation):
    payload = json.loads(saved['registry']['payload'])
    edge = payload['workflow_edges'][0]
    if mutation == 'missing': del edge['downstream']
    elif mutation == 'null': edge['downstream'] = None
    elif mutation == 'malformed': edge['downstream'] = 'invalid'
    elif mutation == 'unregistered': edge['downstream']['integration_id'] = 'absent'
    elif mutation == 'foreign_tenant': edge['downstream']['tenant_id'] = str(database['tenants'][1])
    elif mutation == 'external_registry': edge['registry_id'] = str(uuid4())
    elif mutation == 'unknown_relation': edge['relation'] = 'possibly_calls'
    elif mutation == 'v1_edges': payload['registry_version'] = 'air-dependency-impact-v1'
    elif mutation == 'empty_edges': payload['workflow_edges'] = []
    elif mutation == 'wrong_shape': payload['workflow_edges'] = {}
    else: edge['upstream']['source'] = 'foreign'
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx.put('contract_dependency_registry', uuid4().hex, payload)


def test_database_rejects_foreign_snapshot_and_context_on_workflow_registry(database, repos, saved):
    payload = json.loads(saved['registry']['payload'])
    payload['tenant_id'] = str(database['tenants'][1])
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[1].transaction(database['tenants'][1]) as tx:
            tx.put('contract_dependency_registry', uuid4().hex, payload)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx._connection.execute("SELECT set_config('air.tenant_id', '', true)")
            tx.put('contract_dependency_registry', uuid4().hex, json.loads(saved['registry']['payload']))


@pytest.mark.parametrize('kind', ['registry', 'impact'])
@pytest.mark.parametrize('statement', ['UPDATE air.artifacts SET payload=payload WHERE artifact_id=%s',
                                      'DELETE FROM air.artifacts WHERE artifact_id=%s'])
def test_workflow_registry_and_impact_remain_immutable(database, repos, saved, kind, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx._connection.execute(statement, (saved[kind]['artifact_id'],))


@pytest.mark.parametrize('mutation', ['path', 'root', 'results', 'version'])
def test_reload_recomputes_transitive_paths_and_rejects_forged_results(database, repos, saved, mutation):
    payload = json.loads(saved['impact']['payload'])
    rows = payload['analysis']['downstream_impacts']
    if mutation == 'path': rows[0]['path']['edges'][0]['relation'] = 'invented'
    elif mutation == 'root': rows[0]['root_impact_id'] = '0' * 64
    elif mutation == 'results': rows.clear()
    else: payload['impact_version'] = 'air-dependency-impact-v1'
    with repos[0].transaction(database['tenants'][0]) as tx:
        forged = tx.put('contract_dependency_impact', uuid4().hex, payload)
        with pytest.raises(ImpactError, match='integrity_failure'):
            load_impact(tx, forged['artifact_id'])


def test_failed_bounded_analysis_stores_no_partial_impact(database, repos, saved, monkeypatch):
    import air.dependency_impact as module
    monkeypatch.setattr(module, 'MAX_WORKFLOW_HOPS', 1)
    with repos[0].transaction(database['tenants'][0]) as tx:
        before = tx._connection.execute('SELECT count(*) AS n FROM air.artifacts').fetchone()['n']
        audit_count = len(tx.audit())
        with pytest.raises(ImpactError, match='depth_limit'):
            analyze_and_persist(tx, saved['changes']['artifact_id'], saved['registry']['artifact_id'])
        assert tx._connection.execute('SELECT count(*) AS n FROM air.artifacts').fetchone()['n'] == before
        assert len(tx.audit()) == audit_count


def test_concurrent_workflow_analysis_is_one_immutable_record(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        deps = dependencies()
        registry = register_dependencies(tx, saved['snapshot']['artifact_id'], deps,
            workflow_edges=graph(deps) + [WorkflowEdge(deps[3], deps[5])])
    def analyze(_):
        with repos[0].transaction(database['tenants'][0]) as tx:
            return analyze_and_persist(tx, saved['changes']['artifact_id'], registry['artifact_id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(analyze, range(2)))
    assert first == second
