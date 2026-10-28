from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest

from air.dependency_impact import Dependency, WorkflowEdge
from air.dependency_impact_report import (
    DependencyImpactTraversalReport,
    ImpactTraversalError,
    build_cycle_safe_impact_report,
)
from air.dependency_projection import DependencyProjection, project_dependency_graph
from air.postgres import canonical_json


def dep(name):
    return Dependency(
        integration_id=name,
        mapping_id=f'{name}-mapping',
        location=f'/paths/~1{name}/get/responses/200',
        operation=f'GET /{name}',
    )


def cyclic_projection():
    a, b, c, isolated = (dep(name) for name in ('secret-a', 'secret-b', 'secret-c', 'isolated'))
    value = project_dependency_graph(
        [isolated, c, a, b],
        workflow_edges=[WorkflowEdge(c, a), WorkflowEdge(a, b), WorkflowEdge(b, c)],
    )
    ids = {
        node['dependency']['integration_id']: node['node_id']
        for node in value.to_dict()['nodes']
    }
    return value, ids


def test_cycle_safe_report_is_deterministic_and_bounded_to_reachable_graph():
    projection, ids = cyclic_projection()
    first = build_cycle_safe_impact_report(projection, [ids['secret-a']])
    second = build_cycle_safe_impact_report(projection, [ids['secret-a']])
    assert first == second
    assert first.content_hash == second.content_hash
    payload = first.to_dict()
    assert payload['summary'] == {
        'seed_count': 1,
        'registered_node_count': 4,
        'reachable_node_count': 3,
        'unreachable_registered_node_count': 1,
        'traversed_edge_count': 3,
        'cycle_component_count': 1,
        'impact_layer_count': 3,
        'shortest_path_witness_count': 3,
        'seed_partition_count': 1,
        'declared_convergence_count': 0,
        'declared_branch_count': 0,
        'declared_branch_reach_overlap_count': 0,
        'declared_frontier_node_count': 0,
        'maximum_minimum_hops': 2,
    }
    assert ids['isolated'] not in {node['node_id'] for node in payload['nodes']}
    assert payload['unreachable_registered_node_ids'] == [ids['isolated']]


def test_report_cycle_component_has_exact_hash_evidence_links():
    projection, ids = cyclic_projection()
    payload = build_cycle_safe_impact_report(
        projection, [ids['secret-b'], ids['secret-a']]
    ).to_dict()
    assert payload['seed_node_ids'] == sorted([ids['secret-a'], ids['secret-b']])
    component = payload['cycle_components'][0]
    assert component['node_ids'] == sorted(
        [ids['secret-a'], ids['secret-b'], ids['secret-c']]
    )
    assert len(component['edge_ids']) == 3
    assert all(len(value) == 64 for value in component['edge_ids'])


def test_report_is_redacted_and_has_no_action_authority():
    projection, ids = cyclic_projection()
    report = build_cycle_safe_impact_report(projection, [ids['secret-a']])
    assert 'secret-a' not in report.payload_json
    assert '/secret-a' not in report.payload_json
    assert report.to_dict()['coverage'] == {
        'scope': 'validated_explicit_projection_only',
        'source_warning_count': 0,
        'warnings': [
            'declared_branch_reach_overlap_is_not_path_completeness',
            'declared_branches_are_not_alternative_path_completeness',
            'declared_convergence_is_not_path_completeness',
            'declared_frontier_is_not_downstream_completeness',
            'seed_reachability_is_not_registry_completeness',
            'undeclared_dependencies_are_out_of_scope',
            'unreachable_registered_nodes_omitted_from_impact_body',
        ],
        'cycle_safe_traversal': True,
        'shortest_path_witness_basis': (
            'first_by_sorted_seed_then_declared_edge_id'
        ),
        'impact_layer_basis': 'minimum_declared_hops_from_selected_seeds',
        'seed_partition_basis': 'selected_shortest_path_witness_seed_only',
        'declared_convergence_basis': (
            'multiple_reachable_incoming_traversed_declared_edges_only'
        ),
        'declared_branch_basis': (
            'multiple_reachable_outgoing_traversed_declared_edges_only'
        ),
        'declared_branch_reach_overlap_basis': (
            'shared_reachable_nodes_from_distinct_immediate_declared_'
            'branch_targets_only'
        ),
        'declared_frontier_basis': (
            'reachable_nodes_without_outgoing_traversed_declared_edges_only'
        ),
        'undeclared_dependencies_inferred': False,
        'no_recorded_impact_is_not_safe': True,
    }
    assert report.to_dict()['authority'] == {
        'read_only': True,
        'external_actions': False,
        'repair_authority': False,
        'deployment_authority': False,
    }


def test_unknown_duplicate_or_empty_seeds_fail_closed():
    projection, ids = cyclic_projection()
    with pytest.raises(ImpactTraversalError, match='^impact_report_seed_not_registered$'):
        build_cycle_safe_impact_report(projection, ['0' * 64])
    with pytest.raises(ImpactTraversalError, match='^invalid_impact_report_seeds$'):
        build_cycle_safe_impact_report(projection, [ids['secret-a']] * 2)
    with pytest.raises(ImpactTraversalError, match='^invalid_impact_report_seeds$'):
        build_cycle_safe_impact_report(projection, [])


def test_forged_projection_fails_closed():
    projection, ids = cyclic_projection()
    payload = projection.to_dict()
    payload['edges'][0]['edge_id'] = '0' * 64
    forged = DependencyProjection(canonical_json(payload))
    with pytest.raises(ImpactTraversalError, match='^invalid_dependency_projection$'):
        build_cycle_safe_impact_report(forged, [ids['secret-a']])


def test_report_result_is_frozen():
    projection, ids = cyclic_projection()
    report = build_cycle_safe_impact_report(projection, [ids['secret-a']])
    with pytest.raises(FrozenInstanceError):
        report.payload_json = '{}'
    assert isinstance(report, DependencyImpactTraversalReport)


def test_maximum_bounded_chain_does_not_depend_on_python_recursion_limit():
    dependencies = [dep(f'n-{index:04d}') for index in range(1000)]
    projection = project_dependency_graph(
        dependencies,
        workflow_edges=[
            WorkflowEdge(dependencies[index], dependencies[index + 1])
            for index in range(len(dependencies) - 1)
        ],
    )
    first_id = next(
        node['node_id'] for node in projection.to_dict()['nodes']
        if node['dependency']['integration_id'] == 'n-0000'
    )
    report = build_cycle_safe_impact_report(projection, [first_id]).to_dict()
    assert report['summary']['reachable_node_count'] == 1000
    assert report['summary']['registered_node_count'] == 1000
    assert report['summary']['unreachable_registered_node_count'] == 0
    assert report['summary']['traversed_edge_count'] == 999
    assert report['summary']['maximum_minimum_hops'] == 999
    assert report['summary']['cycle_component_count'] == 0
    assert report['summary']['impact_layer_count'] == 1000
    assert report['summary']['shortest_path_witness_count'] == 1000
    assert report['summary']['seed_partition_count'] == 1
    assert report['summary']['declared_convergence_count'] == 0
    assert report['summary']['declared_branch_count'] == 0
    assert report['summary']['declared_branch_reach_overlap_count'] == 0
    assert report['summary']['declared_frontier_node_count'] == 1
    assert len(report['shortest_path_witnesses']) == 1000
    assert report['unreachable_registered_node_ids'] == []
    assert len(report['impact_layers']) == 1000
    assert 'unreachable_registered_nodes_omitted_from_impact_body' not in (
        report['coverage']['warnings']
    )


def test_completeness_gap_manifest_is_hash_only_and_deterministic():
    projection, ids = cyclic_projection()
    first = build_cycle_safe_impact_report(
        projection, [ids['secret-a']]
    ).to_dict()
    second = build_cycle_safe_impact_report(
        projection, [ids['secret-a']]
    ).to_dict()

    assert first['unreachable_registered_node_ids'] == second[
        'unreachable_registered_node_ids'
    ]
    assert first['unreachable_registered_node_ids'] == [ids['isolated']]
    assert all(
        len(node_id) == 64
        for node_id in first['unreachable_registered_node_ids']
    )
    assert first['summary']['registered_node_count'] == (
        first['summary']['reachable_node_count']
        + first['summary']['unreachable_registered_node_count']
    )


def test_source_coverage_warning_is_exposed_only_as_fixed_code_and_count():
    projection = project_dependency_graph([dep('source-a'), dep('source-b')])
    projection_payload = projection.to_dict()
    projection_payload['coverage']['warnings'] = [
        'caller-private-warning-text'
    ]
    projection = DependencyProjection(canonical_json(projection_payload))
    ids = {
        node['dependency']['integration_id']: node['node_id']
        for node in projection.to_dict()['nodes']
    }
    report = build_cycle_safe_impact_report(projection, [ids['source-a']])

    assert 'caller-private-warning-text' not in report.payload_json
    assert report.to_dict()['coverage']['source_warning_count'] == 1
    assert 'source_projection_has_coverage_warnings' in (
        report.to_dict()['coverage']['warnings']
    )


def test_shortest_path_witnesses_are_hash_only_and_reconstructable():
    projection, ids = cyclic_projection()
    payload = build_cycle_safe_impact_report(
        projection, [ids['secret-a']]
    ).to_dict()
    witnesses = {
        witness['node_id']: witness
        for witness in payload['shortest_path_witnesses']
    }
    root = witnesses[ids['secret-a']]
    assert root == {
        'node_id': ids['secret-a'],
        'witness_seed_node_id': ids['secret-a'],
        'predecessor_node_id': None,
        'predecessor_edge_id': None,
        'minimum_hops': 0,
    }
    for node_id in (ids['secret-b'], ids['secret-c']):
        witness = witnesses[node_id]
        assert witness['witness_seed_node_id'] == ids['secret-a']
        assert len(witness['predecessor_node_id']) == 64
        assert len(witness['predecessor_edge_id']) == 64
        assert witnesses[witness['predecessor_node_id']]['minimum_hops'] == (
            witness['minimum_hops'] - 1
        )


def test_equal_length_witness_choice_is_deterministic():
    seed, left, right, target = (
        dep(name) for name in ('seed', 'left', 'right', 'target')
    )
    projection = project_dependency_graph(
        [target, right, seed, left],
        workflow_edges=[
            WorkflowEdge(right, target),
            WorkflowEdge(seed, right),
            WorkflowEdge(left, target),
            WorkflowEdge(seed, left),
        ],
    )
    payload = projection.to_dict()
    ids = {
        node['dependency']['integration_id']: node['node_id']
        for node in payload['nodes']
    }
    outgoing = sorted(
        [edge for edge in payload['edges']
         if edge['source_node_id'] == ids['seed']],
        key=lambda edge: edge['edge_id'],
    )
    expected_predecessor = outgoing[0]['target_node_id']
    report = build_cycle_safe_impact_report(projection, [ids['seed']]).to_dict()
    target_witness = next(
        witness for witness in report['shortest_path_witnesses']
        if witness['node_id'] == ids['target']
    )
    assert target_witness['predecessor_node_id'] == expected_predecessor
    assert target_witness['minimum_hops'] == 2


def test_impact_layers_are_deterministic_hash_only_and_reconcile_reachable_nodes():
    projection, ids = cyclic_projection()
    first = build_cycle_safe_impact_report(
        projection, [ids['secret-a']]
    ).to_dict()
    second = build_cycle_safe_impact_report(
        projection, [ids['secret-a']]
    ).to_dict()

    assert first['impact_layers'] == second['impact_layers']
    assert [layer['minimum_hops'] for layer in first['impact_layers']] == [0, 1, 2]
    assert first['impact_layers'][0]['node_ids'] == [ids['secret-a']]
    assert all(len(layer['layer_id']) == 64 for layer in first['impact_layers'])
    assert all(
        len(node_id) == 64
        for layer in first['impact_layers']
        for node_id in layer['node_ids']
    )
    assert sorted(
        node_id
        for layer in first['impact_layers']
        for node_id in layer['node_ids']
    ) == sorted(node['node_id'] for node in first['nodes'])


def test_multi_seed_impact_layers_use_minimum_declared_hops():
    projection, ids = cyclic_projection()
    report = build_cycle_safe_impact_report(
        projection, [ids['secret-a'], ids['secret-c']]
    ).to_dict()

    layers = {layer['minimum_hops']: layer for layer in report['impact_layers']}
    assert layers[0]['node_ids'] == sorted([ids['secret-a'], ids['secret-c']])
    assert layers[1]['node_ids'] == [ids['secret-b']]
    assert report['summary']['impact_layer_count'] == 2


def test_seed_partitions_are_deterministic_hash_only_and_reconcile_nodes():
    projection, ids = cyclic_projection()
    first = build_cycle_safe_impact_report(
        projection, [ids['secret-a'], ids['secret-c']]
    ).to_dict()
    second = build_cycle_safe_impact_report(
        projection, [ids['secret-c'], ids['secret-a']]
    ).to_dict()

    assert first['seed_partitions'] == second['seed_partitions']
    assert first['summary']['seed_partition_count'] == 2
    assert [partition['seed_node_id'] for partition in first['seed_partitions']] == (
        sorted([ids['secret-a'], ids['secret-c']])
    )
    assert all(
        len(partition['partition_id']) == 64
        for partition in first['seed_partitions']
    )
    assert sum(
        partition['member_node_count']
        for partition in first['seed_partitions']
    ) == len(first['nodes'])
    assert all(
        len(partition['member_node_ids_hash']) == 64
        for partition in first['seed_partitions']
    )


def test_seed_partition_tie_uses_recorded_witness_not_completeness_claim():
    first_seed, second_seed, shared = (
        dep(name) for name in ('first-seed', 'second-seed', 'shared')
    )
    projection = project_dependency_graph(
        [shared, second_seed, first_seed],
        workflow_edges=[
            WorkflowEdge(second_seed, shared),
            WorkflowEdge(first_seed, shared),
        ],
    )
    ids = {
        node['dependency']['integration_id']: node['node_id']
        for node in projection.to_dict()['nodes']
    }
    payload = build_cycle_safe_impact_report(
        projection, [ids['second-seed'], ids['first-seed']]
    ).to_dict()
    partitions = {
        partition['seed_node_id']: partition
        for partition in payload['seed_partitions']
    }
    selected_seed = min(ids['first-seed'], ids['second-seed'])

    assert partitions[selected_seed]['member_node_count'] == 2
    assert sum(
        partition['member_node_count'] for partition in partitions.values()
    ) == 3
    assert payload['coverage']['seed_partition_basis'] == (
        'selected_shortest_path_witness_seed_only'
    )


def test_declared_convergence_summary_is_deterministic_hash_only_and_bounded():
    seed, left, right, target = (
        dep(name) for name in ('seed', 'left', 'right', 'target')
    )
    projection = project_dependency_graph(
        [target, right, seed, left],
        workflow_edges=[
            WorkflowEdge(right, target),
            WorkflowEdge(seed, right),
            WorkflowEdge(left, target),
            WorkflowEdge(seed, left),
        ],
    )
    ids = {
        node['dependency']['integration_id']: node['node_id']
        for node in projection.to_dict()['nodes']
    }
    first = build_cycle_safe_impact_report(projection, [ids['seed']]).to_dict()
    second = build_cycle_safe_impact_report(projection, [ids['seed']]).to_dict()

    assert first['declared_convergence_summaries'] == (
        second['declared_convergence_summaries']
    )
    assert first['summary']['declared_convergence_count'] == 1
    summary = first['declared_convergence_summaries'][0]
    assert summary['node_id'] == ids['target']
    assert summary['incoming_declared_edge_count'] == 2
    assert len(summary['incoming_declared_edge_ids_hash']) == 64
    assert len(summary['convergence_id']) == 64
    assert 'edge_ids' not in summary


def test_declared_convergence_excludes_unreachable_incoming_edges():
    seed, reachable, unreachable = (
        dep(name) for name in ('seed', 'reachable', 'unreachable')
    )
    projection = project_dependency_graph(
        [unreachable, reachable, seed],
        workflow_edges=[
            WorkflowEdge(seed, reachable),
            WorkflowEdge(unreachable, reachable),
        ],
    )
    ids = {
        node['dependency']['integration_id']: node['node_id']
        for node in projection.to_dict()['nodes']
    }
    payload = build_cycle_safe_impact_report(
        projection, [ids['seed']]
    ).to_dict()

    assert payload['declared_convergence_summaries'] == []
    assert payload['summary']['declared_convergence_count'] == 0
    assert payload['coverage']['declared_convergence_basis'] == (
        'multiple_reachable_incoming_traversed_declared_edges_only'
    )
    assert 'declared_convergence_is_not_path_completeness' in (
        payload['coverage']['warnings']
    )


def test_declared_branch_summary_is_deterministic_hash_only_and_compact():
    seed, left, right, target = (
        dep(name) for name in ('seed', 'left', 'right', 'target')
    )
    projection = project_dependency_graph(
        [target, right, seed, left],
        workflow_edges=[
            WorkflowEdge(seed, left),
            WorkflowEdge(seed, right),
            WorkflowEdge(right, target),
        ],
    )
    ids = {
        node['dependency']['integration_id']: node['node_id']
        for node in projection.to_dict()['nodes']
    }
    first = build_cycle_safe_impact_report(projection, [ids['seed']]).to_dict()
    second = build_cycle_safe_impact_report(projection, [ids['seed']]).to_dict()

    assert first['declared_branch_summaries'] == second[
        'declared_branch_summaries'
    ]
    assert first['summary']['declared_branch_count'] == 1
    summary = first['declared_branch_summaries'][0]
    assert summary['node_id'] == ids['seed']
    assert summary['outgoing_declared_edge_count'] == 2
    assert len(summary['outgoing_declared_edge_ids_hash']) == 64
    assert summary['distinct_target_node_count'] == 2
    target_node_ids = sorted([ids['left'], ids['right']])
    assert summary['target_node_ids_hash'] == sha256(canonical_json({
        'target_node_ids': target_node_ids,
    }).encode()).hexdigest()
    assert len(summary['branch_id']) == 64
    assert 'edge_ids' not in summary
    assert 'target_node_ids' not in summary


def test_declared_branch_summary_excludes_unreachable_outgoing_edges():
    seed, reachable, unreachable = (
        dep(name) for name in ('seed', 'reachable', 'unreachable')
    )
    projection = project_dependency_graph(
        [unreachable, reachable, seed],
        workflow_edges=[
            WorkflowEdge(seed, reachable),
            WorkflowEdge(unreachable, seed),
            WorkflowEdge(unreachable, reachable),
        ],
    )
    ids = {
        node['dependency']['integration_id']: node['node_id']
        for node in projection.to_dict()['nodes']
    }
    payload = build_cycle_safe_impact_report(
        projection, [ids['seed']]
    ).to_dict()

    assert payload['declared_branch_summaries'] == []
    assert payload['summary']['declared_branch_count'] == 0
    assert payload['coverage']['declared_branch_basis'] == (
        'multiple_reachable_outgoing_traversed_declared_edges_only'
    )
    assert 'declared_branches_are_not_alternative_path_completeness' in (
        payload['coverage']['warnings']
    )


def test_declared_branch_target_commitment_reconciles_with_traversed_edges():
    seed, left, right = (dep(name) for name in ('seed', 'left', 'right'))
    projection = project_dependency_graph(
        [right, seed, left],
        workflow_edges=[WorkflowEdge(seed, right), WorkflowEdge(seed, left)],
    )
    ids = {
        node['dependency']['integration_id']: node['node_id']
        for node in projection.to_dict()['nodes']
    }
    payload = build_cycle_safe_impact_report(
        projection, [ids['seed']]
    ).to_dict()
    summary = payload['declared_branch_summaries'][0]
    traversed_target_ids = sorted({
        edge['target_node_id']
        for edge in payload['edges']
        if edge['source_node_id'] == summary['node_id']
    })

    assert summary['distinct_target_node_count'] == len(traversed_target_ids)
    assert summary['target_node_ids_hash'] == sha256(canonical_json({
        'target_node_ids': traversed_target_ids,
    }).encode()).hexdigest()
    assert traversed_target_ids == sorted([ids['left'], ids['right']])


def test_declared_branch_reach_overlap_is_deterministic_hash_only_and_compact():
    seed, left, right, shared, left_only = (
        dep(name)
        for name in ('seed', 'left', 'right', 'shared', 'left-only')
    )
    projection = project_dependency_graph(
        [shared, right, seed, left_only, left],
        workflow_edges=[
            WorkflowEdge(seed, right),
            WorkflowEdge(left, shared),
            WorkflowEdge(seed, left),
            WorkflowEdge(right, shared),
            WorkflowEdge(left, left_only),
        ],
    )
    ids = {
        node['dependency']['integration_id']: node['node_id']
        for node in projection.to_dict()['nodes']
    }
    first = build_cycle_safe_impact_report(projection, [ids['seed']]).to_dict()
    second = build_cycle_safe_impact_report(projection, [ids['seed']]).to_dict()

    assert first['declared_branch_reach_overlap_summaries'] == second[
        'declared_branch_reach_overlap_summaries'
    ]
    assert first['summary']['declared_branch_reach_overlap_count'] == 1
    overlap = first['declared_branch_reach_overlap_summaries'][0]
    assert overlap['branch_id'] == first['declared_branch_summaries'][0][
        'branch_id'
    ]
    assert overlap['branch_target_count'] == 2
    assert overlap['shared_reachable_node_count'] == 1
    assert overlap['shared_reachable_node_ids_hash'] == sha256(canonical_json({
        'node_ids': [ids['shared']],
    }).encode()).hexdigest()
    assert len(overlap['overlap_id']) == 64
    assert 'node_ids' not in overlap


def test_declared_branch_reach_overlap_omits_disjoint_target_cones():
    seed, left, right = (dep(name) for name in ('seed', 'left', 'right'))
    projection = project_dependency_graph(
        [right, seed, left],
        workflow_edges=[WorkflowEdge(seed, right), WorkflowEdge(seed, left)],
    )
    ids = {
        node['dependency']['integration_id']: node['node_id']
        for node in projection.to_dict()['nodes']
    }
    payload = build_cycle_safe_impact_report(
        projection, [ids['seed']]
    ).to_dict()

    assert payload['declared_branch_reach_overlap_summaries'] == []
    assert payload['summary']['declared_branch_reach_overlap_count'] == 0
    assert payload['coverage']['declared_branch_reach_overlap_basis'] == (
        'shared_reachable_nodes_from_distinct_immediate_declared_'
        'branch_targets_only'
    )
    assert 'declared_branch_reach_overlap_is_not_path_completeness' in (
        payload['coverage']['warnings']
    )


def test_declared_frontier_summary_is_deterministic_hash_only_and_compact():
    seed, left, right, target = (
        dep(name) for name in ('seed', 'left', 'right', 'target')
    )
    projection = project_dependency_graph(
        [target, right, seed, left],
        workflow_edges=[
            WorkflowEdge(seed, left),
            WorkflowEdge(seed, right),
            WorkflowEdge(right, target),
        ],
    )
    ids = {
        node['dependency']['integration_id']: node['node_id']
        for node in projection.to_dict()['nodes']
    }
    first = build_cycle_safe_impact_report(projection, [ids['seed']]).to_dict()
    second = build_cycle_safe_impact_report(projection, [ids['seed']]).to_dict()

    assert first['declared_frontier_summary'] == (
        second['declared_frontier_summary']
    )
    summary = first['declared_frontier_summary']
    assert summary['node_count'] == 2
    assert first['summary']['declared_frontier_node_count'] == 2
    assert len(summary['node_ids_hash']) == 64
    assert len(summary['frontier_id']) == 64
    assert 'node_ids' not in summary


def test_declared_frontier_summary_does_not_treat_cycles_as_terminals():
    projection, ids = cyclic_projection()
    payload = build_cycle_safe_impact_report(
        projection, [ids['secret-a']]
    ).to_dict()

    assert payload['declared_frontier_summary']['node_count'] == 0
    assert payload['summary']['declared_frontier_node_count'] == 0
    assert 'declared_frontier_is_not_downstream_completeness' in (
        payload['coverage']['warnings']
    )
