from dataclasses import FrozenInstanceError, asdict

import pytest

from air.dependency_impact import Dependency, ImpactReport, WorkflowEdge, _digest
from air.dependency_projection import ProjectionError, project_dependency_graph
from air.postgres import canonical_json


def dep(name):
    return Dependency(
        integration_id=name,
        mapping_id='item-id',
        location='/paths/~1items/get/responses/200',
        operation='GET /items',
    )


def impact_report(dependencies, direct_dependency, *, tamper=False):
    normalized = sorted((asdict(value) for value in dependencies), key=canonical_json)
    core = {
        'change_id': 'c' * 64,
        'change_location': '/paths/~1items/get/responses/200',
        'change_type': 'RESPONSE_REMOVED',
        'classification': 'BREAKING',
        'dependency': asdict(direct_dependency),
        'match': 'LOCATION_OVERLAP',
        'reason': 'Recorded location overlap requires review.',
    }
    impact_id = _digest(core)
    if tamper:
        impact_id = '0' * 64
    payload = {
        'impact_version': 'air-dependency-impact-v1',
        'change_set_hash': 'a' * 64,
        'dependencies_hash': _digest({'dependencies': normalized}),
        'impacts': [{'impact_id': impact_id, **core}],
        'coverage_warnings': ['registry_is_caller_supplied'],
        'scope': 'explicit_registry_only',
        'review_required': True,
    }
    return ImpactReport(canonical_json(payload))


def test_projection_is_deterministic_across_input_order():
    a, b, c = dep('a'), dep('b'), dep('c')
    edges = [WorkflowEdge(a, b), WorkflowEdge(b, c)]
    first = project_dependency_graph([c, a, b], workflow_edges=reversed(edges))
    second = project_dependency_graph([a, b, c], workflow_edges=edges)
    assert first.payload_json == second.payload_json
    assert first.content_hash == second.content_hash
    assert len(first.to_dict()['nodes']) == 3
    assert len(first.to_dict()['edges']) == 2


def test_projection_marks_only_recorded_direct_review():
    a, b = dep('a'), dep('b')
    projection = project_dependency_graph(
        [a, b], impact_report=impact_report([a, b], a)
    ).to_dict()
    by_name = {node['dependency']['integration_id']: node for node in projection['nodes']}
    assert by_name['a']['impact_status'] == 'direct_review'
    assert len(by_name['a']['direct_impact_ids']) == 1
    assert by_name['b']['impact_status'] == 'no_recorded_impact'
    assert projection['coverage'] == {
        'scope': 'explicit_registry_only',
        'warnings': ['registry_is_caller_supplied'],
        'no_recorded_impact_is_not_safe': True,
        'dependency_discovery_performed': False,
    }


def test_projection_without_impact_report_is_explicitly_unknown():
    projection = project_dependency_graph([dep('a')]).to_dict()
    assert projection['impact_report_hash'] is None
    assert projection['nodes'][0]['impact_status'] == 'no_recorded_impact'
    assert projection['coverage']['no_recorded_impact_is_not_safe'] is True


def test_projection_rejects_registry_mismatch():
    a, b = dep('a'), dep('b')
    with pytest.raises(ProjectionError, match='^projection_registry_mismatch$'):
        project_dependency_graph([a], impact_report=impact_report([a, b], a))


def test_projection_rejects_tampered_impact_identity():
    a = dep('a')
    with pytest.raises(ProjectionError, match='^impact_identity_mismatch$'):
        project_dependency_graph([a], impact_report=impact_report([a], a, tamper=True))


def test_projection_rejects_unregistered_edge_endpoint():
    a, b = dep('a'), dep('b')
    with pytest.raises(ProjectionError, match='^workflow_endpoint_not_registered$'):
        project_dependency_graph([a], workflow_edges=[WorkflowEdge(a, b)])


def test_projection_rejects_non_report_input():
    with pytest.raises(ProjectionError, match='^invalid_impact_report$'):
        project_dependency_graph([dep('a')], impact_report={})


def test_projection_result_is_frozen():
    report = project_dependency_graph([dep('a')])
    with pytest.raises(FrozenInstanceError):
        report.payload_json = '{}'
