"""PostgreSQL integrity coverage for persisted AIR-25 dependency projections."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

import psycopg
import pytest

from air.change_evidence import detect_and_persist
from air.dependency_impact import (
    Dependency,
    WorkflowEdge,
    analyze_and_persist,
    register_dependencies,
    _digest,
)
from air.dependency_projection import (
    ProjectionError,
    load_projection,
    project_and_persist,
)
from air.dependency_visualization import (
    VisualizationError,
    load_visualization,
    visualize_and_persist,
)
from air.observer import ContractSnapshot
from air.postgres import canonical_json

pytestmark = pytest.mark.postgres


def _contract(*, removed=False):
    return {
        'openapi': '3.1.0',
        'info': {'title': 'Projection fixture', 'version': '1'},
        'paths': {} if removed else {
            '/items': {'get': {'responses': {'200': {'description': 'OK'}}}},
        },
    }


def _snapshot(tx, contract):
    value = canonical_json(contract)
    return ContractSnapshot(
        tx.tenant_id, 'projection-fixture', 'https://example.com',
        datetime.now(timezone.utc).isoformat(), '8.8.8.8', 0, value,
        sha256(value.encode()).hexdigest(),
    ).persist(tx, uuid4().hex)


def _dependencies(prefix=''):
    upstream = Dependency(
        prefix + 'billing', 'fetch-items', '/paths/~1items/get',
        'GET /items', 'workflow')
    downstream = Dependency(
        prefix + 'ledger', 'consume-items', '/paths/~1items/get',
        'GET /items', 'workflow')
    return upstream, downstream


def _evidence(tx, prefix=''):
    previous = _snapshot(tx, _contract())
    current = _snapshot(tx, _contract(removed=True))
    change = detect_and_persist(tx, previous['artifact_id'], current['artifact_id'])
    upstream, downstream = _dependencies(prefix)
    registry = register_dependencies(
        tx, previous['artifact_id'], [upstream, downstream],
        workflow_edges=[WorkflowEdge(upstream, downstream)],
    )
    impact = analyze_and_persist(tx, change['artifact_id'], registry['artifact_id'])
    return {'registry': registry, 'impact': impact}


@pytest.fixture
def saved(database, repos):
    with repos[0].transaction(database['tenants'][0]) as tx:
        return _evidence(tx)


def test_projection_persistence_reload_idempotence_and_audit(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        first = project_and_persist(
            tx, saved['registry']['artifact_id'], impact_id=saved['impact']['artifact_id'])
        repeated = project_and_persist(
            tx, saved['registry']['artifact_id'], impact_id=saved['impact']['artifact_id'])
        assert repeated == first
        assert load_projection(tx, first['artifact_id']) == first
        payload = json.loads(first['payload'])
        assert payload['tenant_id'] == str(tx.tenant_id)
        assert payload['registry'] == {
            'artifact_id': str(saved['registry']['artifact_id']),
            'artifact_hash': saved['registry']['content_hash'],
        }
        projection = json.loads(payload['projection_payload'])
        assert projection['impact_summary']['recorded_review_node_count'] == 2
        assert projection['authority']['read_only'] is True
        assert len([event for event in tx.audit()
                    if event['artifact_id'] == first['artifact_id']]) == 1


def test_registry_only_projection_retains_explicit_unknown_coverage(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        record = project_and_persist(tx, saved['registry']['artifact_id'])
        payload = json.loads(record['payload'])
        projection = json.loads(payload['projection_payload'])
        assert payload['impact'] is None
        assert projection['impact_report_hash'] is None
        assert projection['impact_summary']['recorded_review_node_count'] == 0
        assert projection['impact_summary']['no_recorded_impact_node_count'] == 2
        assert load_projection(tx, record['artifact_id']) == record


def test_other_tenant_cannot_read_or_project_foreign_evidence(database, repos, saved):
    with repos[1].transaction(database['tenants'][1]) as tx:
        with pytest.raises(ProjectionError, match='evidence_not_found_or_invalid'):
            project_and_persist(
                tx, saved['registry']['artifact_id'],
                impact_id=saved['impact']['artifact_id'])
        assert tx._connection.execute(
            "SELECT * FROM air.artifacts WHERE kind='dependency_projection'"
        ).fetchall() == []


def test_projection_rejects_impact_from_another_registry(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        other = _evidence(tx, 'other-')
        with pytest.raises(ProjectionError, match='impact_registry_mismatch'):
            project_and_persist(
                tx, saved['registry']['artifact_id'],
                impact_id=other['impact']['artifact_id'])


@pytest.mark.parametrize('mutation', [
    'tenant', 'registry_hash', 'impact_hash', 'impact_registry', 'extra_key',
])
def test_database_rejects_forged_projection_envelopes(
        database, repos, saved, mutation):
    with repos[0].transaction(database['tenants'][0]) as tx:
        original = project_and_persist(
            tx, saved['registry']['artifact_id'], impact_id=saved['impact']['artifact_id'])
        payload = json.loads(original['payload'])
        if mutation == 'tenant':
            payload['tenant_id'] = str(database['tenants'][1])
        elif mutation == 'registry_hash':
            payload['registry']['artifact_hash'] = '0' * 64
        elif mutation == 'impact_hash':
            payload['impact']['artifact_hash'] = '0' * 64
        elif mutation == 'impact_registry':
            other = _evidence(tx, 'other-')
            payload['impact'] = {
                'artifact_id': str(other['impact']['artifact_id']),
                'artifact_hash': other['impact']['content_hash'],
            }
        else:
            payload['unexpected'] = True
        with pytest.raises(psycopg.errors.CheckViolation):
            tx.put('dependency_projection', _digest(payload), payload)


def test_reload_recomputes_and_rejects_forged_projection(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        original = project_and_persist(
            tx, saved['registry']['artifact_id'], impact_id=saved['impact']['artifact_id'])
        payload = json.loads(original['payload'])
        projection = json.loads(payload['projection_payload'])
        projection['nodes'][0]['impact_status'] = 'no_recorded_impact'
        payload['projection_payload'] = canonical_json(projection)
        payload['projection_hash'] = sha256(
            payload['projection_payload'].encode()).hexdigest()
        forged = tx.put('dependency_projection', _digest(payload), payload)
        with pytest.raises(ProjectionError, match='invalid_persisted_projection'):
            load_projection(tx, forged['artifact_id'])


def test_persisted_projection_is_append_only(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        record = project_and_persist(
            tx, saved['registry']['artifact_id'], impact_id=saved['impact']['artifact_id'])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx._connection.execute(
                'DELETE FROM air.artifacts WHERE artifact_id=%s',
                (record['artifact_id'],),
            )


def _saved_visualization(tx, saved):
    projection = project_and_persist(
        tx, saved['registry']['artifact_id'], impact_id=saved['impact']['artifact_id'])
    return projection, visualize_and_persist(tx, projection['artifact_id'])


def test_visualization_persistence_reload_idempotence_and_audit(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        projection, first = _saved_visualization(tx, saved)
        repeated = visualize_and_persist(tx, projection['artifact_id'])
        assert repeated == first
        assert load_visualization(tx, first['artifact_id']) == first
        payload = json.loads(first['payload'])
        assert payload['tenant_id'] == str(tx.tenant_id)
        assert payload['projection'] == {
            'artifact_id': str(projection['artifact_id']),
            'artifact_hash': projection['content_hash'],
        }
        visualization = json.loads(payload['visualization_payload'])
        assert visualization['coverage']['raw_dependency_metadata_included'] is False
        assert visualization['authority']['external_actions'] is False
        assert len([event for event in tx.audit()
                    if event['artifact_id'] == first['artifact_id']]) == 1


def test_other_tenant_cannot_read_or_visualize_foreign_projection(
        database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        projection, visualization = _saved_visualization(tx, saved)
    with repos[1].transaction(database['tenants'][1]) as tx:
        with pytest.raises(VisualizationError, match='persistence_rejected'):
            visualize_and_persist(tx, projection['artifact_id'])
        with pytest.raises(VisualizationError, match='not_found_or_not_authorized'):
            load_visualization(tx, visualization['artifact_id'])
        assert tx._connection.execute(
            "SELECT * FROM air.artifacts WHERE kind='dependency_visualization'"
        ).fetchall() == []


@pytest.mark.parametrize('mutation', [
    'tenant', 'projection_hash', 'visualization_hash', 'extra_key',
])
def test_database_rejects_forged_visualization_envelopes(
        database, repos, saved, mutation):
    with repos[0].transaction(database['tenants'][0]) as tx:
        _, original = _saved_visualization(tx, saved)
        payload = json.loads(original['payload'])
        if mutation == 'tenant':
            payload['tenant_id'] = str(database['tenants'][1])
        elif mutation == 'projection_hash':
            payload['projection']['artifact_hash'] = '0' * 64
        elif mutation == 'visualization_hash':
            payload['visualization_hash'] = '0' * 64
        else:
            payload['unexpected'] = True
        with pytest.raises((psycopg.errors.CheckViolation,
                            psycopg.errors.InsufficientPrivilege)):
            tx.put('dependency_visualization', _digest(payload), payload)


def test_reload_recomputes_and_rejects_forged_visualization(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        _, original = _saved_visualization(tx, saved)
        payload = json.loads(original['payload'])
        visualization = json.loads(payload['visualization_payload'])
        visualization['nodes'][0]['review_lane'] = 'no_recorded_impact'
        payload['visualization_payload'] = canonical_json(visualization)
        payload['visualization_hash'] = sha256(
            payload['visualization_payload'].encode()).hexdigest()
        forged = tx.put('dependency_visualization', _digest(payload), payload)
        with pytest.raises(VisualizationError, match='invalid_persisted_visualization'):
            load_visualization(tx, forged['artifact_id'])


def test_persisted_visualization_is_append_only(database, repos, saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        _, record = _saved_visualization(tx, saved)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx._connection.execute(
                'DELETE FROM air.artifacts WHERE artifact_id=%s',
                (record['artifact_id'],),
            )
