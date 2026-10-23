from dataclasses import FrozenInstanceError, asdict
import json

import pytest

from air.dependency_impact import Dependency, ImpactReport, WorkflowEdge, _digest
from air.dependency_projection import DependencyProjection, project_dependency_graph
from air.dependency_visualization import (
    VisualizationError,
    visualize_dependency_projection,
)
from air.postgres import canonical_json


def dep(name):
    return Dependency(
        integration_id=name,
        mapping_id=f'{name}-mapping',
        location=f'/paths/~1{name}/get/responses/200',
        operation=f'GET /{name}',
    )


def report(dependencies, direct, downstream):
    normalized = sorted((asdict(value) for value in dependencies), key=canonical_json)
    direct_core = {
        'change_id': 'c' * 64,
        'dependency': asdict(direct),
    }
    downstream_core = {
        'change_id': 'c' * 64,
        'dependency': asdict(downstream),
    }
    payload = {
        'dependencies_hash': _digest({'dependencies': normalized}),
        'impacts': [{'impact_id': _digest(direct_core), **direct_core}],
        'downstream_impacts': [
            {'impact_id': _digest(downstream_core), **downstream_core}
        ],
        'coverage_warnings': ['registry_is_caller_supplied'],
    }
    return ImpactReport(canonical_json(payload))


def projection():
    a, b, c = dep('secret-a'), dep('secret-b'), dep('secret-c')
    return project_dependency_graph(
        [c, a, b],
        workflow_edges=[WorkflowEdge(a, b), WorkflowEdge(b, c)],
        impact_report=report([a, b, c], a, b),
    )


def forged(value, update):
    payload = value.to_dict()
    update(payload)
    return DependencyProjection(canonical_json(payload))


def test_visualization_is_deterministic_redacted_and_content_addressed():
    first = visualize_dependency_projection(projection())
    second = visualize_dependency_projection(projection())
    assert first.payload_json == second.payload_json
    assert first.content_hash == second.content_hash
    assert 'secret-a' not in first.payload_json
    assert '/secret-a' not in first.payload_json
    assert first.to_dict()['projection_hash'] == projection().content_hash


def test_visualization_assigns_stable_review_lanes_and_aliases():
    result = visualize_dependency_projection(projection()).to_dict()
    assert [node['visual_id'] for node in result['nodes']] == [
        'node-0001', 'node-0002', 'node-0003'
    ]
    lanes = {lane['lane']: lane['visual_node_ids'] for lane in result['review_lanes']}
    assert sorted(map(len, lanes.values())) == [1, 1, 1]
    assert {node['review_lane'] for node in result['nodes']} == {
        'direct_review', 'transitive_review', 'no_recorded_impact'
    }


def test_visualization_edges_use_only_opaque_aliases():
    result = visualize_dependency_projection(projection()).to_dict()
    assert len(result['edges']) == 2
    assert all(edge['relation'] == 'consumes_output' for edge in result['edges'])
    assert all(edge['source_visual_id'].startswith('node-') for edge in result['edges'])
    assert all(edge['target_visual_id'].startswith('node-') for edge in result['edges'])


def test_visualization_exposes_limits_without_safety_or_action_claims():
    result = visualize_dependency_projection(projection()).to_dict()
    assert result['coverage'] == {
        'scope': 'validated_explicit_projection_only',
        'source_warning_count': 1,
        'raw_dependency_metadata_included': False,
        'projection_origin_authenticated': False,
        'no_recorded_impact_is_not_safe': True,
        'dependency_discovery_performed': False,
    }
    assert result['authority'] == {
        'read_only': True,
        'external_actions': False,
        'repair_authority': False,
        'deployment_authority': False,
    }


def test_visualization_result_is_frozen():
    result = visualize_dependency_projection(projection())
    with pytest.raises(FrozenInstanceError):
        result.payload_json = '{}'


def test_visualization_rejects_non_projection_and_noncanonical_json():
    with pytest.raises(VisualizationError, match='^invalid_dependency_projection$'):
        visualize_dependency_projection({})
    value = projection()
    noncanonical = DependencyProjection(json.dumps(value.to_dict(), indent=2))
    with pytest.raises(
        VisualizationError, match='^noncanonical_dependency_projection$'
    ):
        visualize_dependency_projection(noncanonical)


def test_visualization_rejects_forged_node_identity():
    value = forged(projection(), lambda payload: payload['nodes'][0].update(
        node_id='0' * 64
    ))
    with pytest.raises(
        VisualizationError, match='^projection_node_identity_mismatch$'
    ):
        visualize_dependency_projection(value)


def test_visualization_rejects_forged_status():
    value = forged(projection(), lambda payload: payload['nodes'][0].update(
        impact_status='no_recorded_impact'
    ))
    with pytest.raises(VisualizationError, match='^projection_status_mismatch$'):
        visualize_dependency_projection(value)


def test_visualization_rejects_forged_edge_identity():
    value = forged(projection(), lambda payload: payload['edges'][0].update(
        edge_id='0' * 64
    ))
    with pytest.raises(
        VisualizationError, match='^projection_edge_identity_mismatch$'
    ):
        visualize_dependency_projection(value)


def test_visualization_rejects_forged_summary():
    value = forged(projection(), lambda payload: payload['impact_summary'].update(
        dependency_count=999
    ))
    with pytest.raises(VisualizationError, match='^projection_summary_mismatch$'):
        visualize_dependency_projection(value)


def test_visualization_rejects_action_authority():
    value = forged(projection(), lambda payload: payload['authority'].update(
        external_actions=True
    ))
    with pytest.raises(VisualizationError, match='^invalid_projection_authority$'):
        visualize_dependency_projection(value)
