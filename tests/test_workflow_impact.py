from copy import deepcopy
from dataclasses import asdict

import pytest

from air.change_intelligence import compare_openapi
from air.dependency_impact import (Dependency, WorkflowEdge, ImpactError, analyze_changes,
    WORKFLOW_VERSION, _digest, _edge)


def contract(count=8):
    return {'openapi': '3.1.0', 'info': {'title': 'Test', 'version': '1'},
        'paths': {f'/node{i}': {'get': {'responses': {'200': {'description': 'ok'}}}} for i in range(count)}}


def dependencies(count=8):
    return [Dependency(f'node{i}', 'read', f'/paths/~1node{i}/get', f'GET /node{i}',
                       'adapter' if i == 0 else 'workflow') for i in range(count)]


def changes(count=8, removed=(0,)):
    old = contract(count); new = deepcopy(old)
    for i in removed: del new['paths'][f'/node{i}']
    return compare_openapi(old, new)


def run(pairs, count=8, removed=(0,)):
    deps = dependencies(count)
    return analyze_changes(changes(count, removed), deps,
                           workflow_edges=[WorkflowEdge(deps[a], deps[b]) for a, b in pairs])


@pytest.mark.parametrize('hops', [1, 2, 5])
def test_one_two_and_multi_hop_impact(hops):
    report = run([(i, i + 1) for i in range(hops)]).to_dict()
    assert report['impact_version'] == WORKFLOW_VERSION
    assert len(report['impacts']) == 1
    assert len(report['downstream_impacts']) == hops
    assert {r['hops'] for r in report['downstream_impacts']} == set(range(1, hops + 1))
    assert report['review_required']


def test_branching_convergence_and_duplicate_edges_deduplicate_nodes():
    result = run([(0, 1), (0, 2), (1, 3), (2, 3), (0, 1)]).to_dict()
    rows = result['downstream_impacts']
    assert {r['dependency']['integration_id'] for r in rows} == {'node1', 'node2', 'node3'}
    assert len(rows) == 3
    assert next(r for r in rows if r['dependency']['integration_id'] == 'node3')['hops'] == 2


def test_canonical_shortest_path_wins_over_longer_path():
    report = run([(0, 1), (1, 2), (2, 3), (0, 3)]).to_dict()
    target = next(r for r in report['downstream_impacts'] if r['dependency']['integration_id'] == 'node3')
    assert target['hops'] == 1


@pytest.mark.parametrize('pairs,expected', [([(0, 0)], 0), ([(0, 1), (1, 0)], 1),
    ([(0, 1), (1, 2), (2, 1), (2, 2)], 2), ([(4, 5), (5, 4)], 0)])
def test_cycles_self_edges_and_unreachable_cycles_terminate(pairs, expected):
    report = run(pairs).to_dict()
    assert len(report['downstream_impacts']) == expected
    assert report['traversal']['examined_edges'] <= len(pairs)


def test_every_hop_has_registered_provenance_and_original_change():
    report = run([(0, 1), (1, 2), (2, 3)]).to_dict()
    seed, = report['impacts']
    for row in report['downstream_impacts']:
        assert row['change_id'] == seed['change_id']
        assert row['root_impact_id'] == seed['impact_id']
        assert row['classification'] == 'BREAKING' and row['match'] == 'TRANSITIVE_REVIEW'
        assert row['root_dependency_id'] == _digest(seed['dependency'])
        assert row['path']['nodes'][0] == row['root_dependency_id']
        assert row['path']['nodes'][-1] == _digest(row['dependency']) == row['dependency_id']
        assert row['hops'] == len(row['path']['edges']) == len(row['path']['nodes']) - 1
        for index, edge in enumerate(row['path']['edges']):
            assert edge['edge_id'] == _digest({k: edge[k] for k in ('upstream', 'downstream', 'relation')})
            assert _digest(edge['upstream']) == row['path']['nodes'][index]
            assert _digest(edge['downstream']) == row['path']['nodes'][index + 1]


def test_database_input_order_cannot_change_result_or_path():
    deps = dependencies(); edges = [WorkflowEdge(deps[a], deps[b]) for a,b in [(0,1),(0,2),(1,3),(2,3)]]
    first = analyze_changes(changes(), deps, workflow_edges=edges)
    second = analyze_changes(changes(), reversed(deps), workflow_edges=list(reversed(edges)) + [edges[0]])
    assert first == second and first.content_hash == second.content_hash
    report = first.to_dict(); report['downstream_impacts'].clear()
    assert first.to_dict()['downstream_impacts']


def test_distinct_original_changes_keep_distinct_evidence():
    report = run([(0, 2), (1, 2)], removed=(0, 1)).to_dict()
    assert len(report['downstream_impacts']) == 2
    assert len({r['change_id'] for r in report['downstream_impacts']}) == 2


def test_multiple_seeds_for_same_change_select_one_explanation():
    deps = dependencies()
    extra = Dependency('other-root', 'read', '/paths/~1node0', None, 'integration')
    report = analyze_changes(changes(), deps + [extra], workflow_edges=[WorkflowEdge(deps[0], deps[1]),
                            WorkflowEdge(extra, deps[1])]).to_dict()
    assert len(report['impacts']) == 2 and len(report['downstream_impacts']) == 1
    chosen = min(_digest(asdict(deps[0])), _digest(asdict(extra)))
    assert report['downstream_impacts'][0]['root_dependency_id'] == chosen


def test_missing_relationship_does_not_invent_reachability():
    report = run([(1, 2)]).to_dict()
    assert report['downstream_impacts'] == []
    assert report['scope'] == 'explicit_registry_only'
    assert report['review_required']


def test_missing_endpoint_is_rejected():
    deps = dependencies()
    with pytest.raises(ImpactError, match='endpoint_not_registered'):
        analyze_changes(changes(), deps[:2], workflow_edges=[WorkflowEdge(deps[0], deps[2])])


@pytest.mark.parametrize('value', [None, {}, {'upstream': {}},
    {'upstream': {}, 'downstream': {}, 'relation': 'consumes_output'},
    {'upstream': {}, 'downstream': {}, 'relation': 'unknown', 'tenant_id': 'foreign'}])
def test_malformed_or_ambiguous_edge(value):
    with pytest.raises(ImpactError):
        _edge(value)


def test_unsupported_relation_and_endpoint_types():
    deps = dependencies()
    with pytest.raises(ImpactError, match='relation'):
        WorkflowEdge(deps[0], deps[1], 'maybe_calls')
    with pytest.raises(ImpactError, match='endpoint'):
        WorkflowEdge({}, deps[1])


@pytest.mark.parametrize('limit,value,pairs,error', [
    ('MAX_WORKFLOW_EDGES', 1, [(0,1),(1,2)], 'edge_limit'),
    ('MAX_WORKFLOW_HOPS', 1, [(0,1),(1,2)], 'depth_limit'),
    ('MAX_TRAVERSAL_STEPS', 1, [(0,1),(1,2)], 'traversal_limit'),
    ('MAX_IMPACTS', 1, [(0,1)], 'result_limit'),
])
def test_bounds_fail_instead_of_returning_partial_results(monkeypatch, limit, value, pairs, error):
    import air.dependency_impact as module
    monkeypatch.setattr(module, limit, value)
    with pytest.raises(ImpactError, match=error):
        run(pairs)


def test_depth_boundary_accepts_complete_graph_and_back_edges(monkeypatch):
    import air.dependency_impact as module
    monkeypatch.setattr(module, 'MAX_WORKFLOW_HOPS', 2)
    report = run([(0,1),(1,2),(2,0),(2,2),(0,3),(3,2)]).to_dict()
    assert len(report['downstream_impacts']) == 3
    assert max(r['hops'] for r in report['downstream_impacts']) == 2


def test_no_change_nonbreaking_and_legacy_direct_report():
    deps = dependencies(); old = contract(); new = deepcopy(old)
    new['paths']['/additional'] = old['paths']['/node0']
    for change in (compare_openapi(old, old), compare_openapi(old, new)):
        report = analyze_changes(change, deps, workflow_edges=[WorkflowEdge(deps[0], deps[1])]).to_dict()
        assert report['impacts'] == [] and report['downstream_impacts'] == []
        assert not report['review_required']
    assert 'downstream_impacts' not in analyze_changes(changes(), deps).to_dict()


def test_path_evidence_byte_budget_fails_before_materializing_large_output(monkeypatch):
    import air.dependency_impact as module
    monkeypatch.setattr(module, 'MAX_WORKFLOW_OUTPUT_BYTES', 100)
    with pytest.raises(ImpactError, match='evidence_size_limit'):
        run([(0,1),(1,2),(2,3)])
