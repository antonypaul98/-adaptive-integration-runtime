"""Cycle-safe impact reports over validated explicit dependency projections.

The report traverses only already-declared workflow edges.  It does not inspect
production systems, discover dependencies, or treat missing recorded impact as
evidence of safety.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Iterable

from air.dependency_impact import MAX_DEPENDENCIES, _digest
from air.dependency_projection import DependencyProjection
from air.dependency_visualization import VisualizationError, _validated_projection
from air.postgres import canonical_json

IMPACT_REPORT_VERSION = 'air-dependency-impact-traversal-v2'
_HEX_64 = re.compile(r'[0-9a-f]{64}')


class ImpactTraversalError(ValueError):
    """Fixed codes only; never include dependency or contract content."""


@dataclass(frozen=True)
class DependencyImpactTraversalReport:
    payload_json: str

    def to_dict(self):
        return json.loads(self.payload_json)

    @property
    def content_hash(self):
        return sha256(self.payload_json.encode()).hexdigest()


def _seeds(values: Iterable[str], known: set[str]) -> list[str]:
    try:
        result = list(values)
    except TypeError:
        raise ImpactTraversalError('invalid_impact_report_seeds') from None
    if (not result or len(result) > MAX_DEPENDENCIES
            or any(not isinstance(value, str) or not _HEX_64.fullmatch(value)
                   for value in result)
            or len(set(result)) != len(result)):
        raise ImpactTraversalError('invalid_impact_report_seeds')
    if any(value not in known for value in result):
        raise ImpactTraversalError('impact_report_seed_not_registered')
    return sorted(result)


def _cyclic_components(nodes: set[str], edges: list[dict]) -> list[dict]:
    """Return deterministic strongly-connected components containing cycles."""
    adjacency = {node: [] for node in nodes}
    edge_by_pair: dict[tuple[str, str], list[str]] = {}
    for edge in edges:
        source = edge['source_node_id']
        target = edge['target_node_id']
        adjacency[source].append(target)
        edge_by_pair.setdefault((source, target), []).append(edge['edge_id'])
    for targets in adjacency.values():
        targets.sort()

    reverse = {node: [] for node in nodes}
    for source, targets in adjacency.items():
        for target in targets:
            reverse[target].append(source)
    for sources in reverse.values():
        sources.sort()

    # Iterative Kosaraju traversal keeps the 1,000-node contract independent of
    # Python's recursion limit while preserving deterministic visit order.
    seen: set[str] = set()
    order: list[str] = []
    for root in sorted(nodes):
        if root in seen:
            continue
        stack = [(root, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                order.append(node)
                continue
            if node in seen:
                continue
            seen.add(node)
            stack.append((node, True))
            for target in reversed(adjacency[node]):
                if target not in seen:
                    stack.append((target, False))

    assigned: set[str] = set()
    components: list[list[str]] = []
    for root in reversed(order):
        if root in assigned:
            continue
        component = []
        stack = [root]
        assigned.add(root)
        while stack:
            node = stack.pop()
            component.append(node)
            for source in reversed(reverse[node]):
                if source not in assigned:
                    assigned.add(source)
                    stack.append(source)
        components.append(sorted(component))

    result = []
    for component in components:
        members = set(component)
        internal_edges = sorted(
            edge_id
            for (source, target), edge_ids in edge_by_pair.items()
            if source in members and target in members
            for edge_id in edge_ids
        )
        if len(component) == 1 and not internal_edges:
            continue
        if len(component) == 1:
            only = component[0]
            internal_edges = sorted(edge_by_pair.get((only, only), ()))
            if not internal_edges:
                continue
        core = {'node_ids': component, 'edge_ids': internal_edges}
        result.append({'component_id': _digest(core), **core})
    return sorted(result, key=lambda value: value['component_id'])


def build_cycle_safe_impact_report(
    projection: DependencyProjection,
    seed_node_ids: Iterable[str],
) -> DependencyImpactTraversalReport:
    """Traverse declared downstream edges once and emit hash-only evidence."""
    try:
        source = _validated_projection(projection)
    except VisualizationError as exc:
        raise ImpactTraversalError('invalid_dependency_projection') from exc

    by_id = {node['node_id']: node for node in source['nodes']}
    seeds = _seeds(seed_node_ids, set(by_id))
    adjacency = {node_id: [] for node_id in by_id}
    for edge in source['edges']:
        adjacency[edge['source_node_id']].append(edge)
    for edges in adjacency.values():
        edges.sort(key=lambda value: value['edge_id'])

    distances = {node_id: 0 for node_id in seeds}
    witnesses = {
        node_id: {
            'node_id': node_id,
            'witness_seed_node_id': node_id,
            'predecessor_node_id': None,
            'predecessor_edge_id': None,
            'minimum_hops': 0,
        }
        for node_id in seeds
    }
    queue = deque(seeds)
    traversed: dict[str, dict] = {}
    while queue:
        source_id = queue.popleft()
        for edge in adjacency[source_id]:
            traversed[edge['edge_id']] = edge
            target = edge['target_node_id']
            if target not in distances:
                distances[target] = distances[source_id] + 1
                witnesses[target] = {
                    'node_id': target,
                    'witness_seed_node_id': witnesses[source_id][
                        'witness_seed_node_id'
                    ],
                    'predecessor_node_id': source_id,
                    'predecessor_edge_id': edge['edge_id'],
                    'minimum_hops': distances[target],
                }
                queue.append(target)

    reachable = set(distances)
    edges = sorted(traversed.values(), key=lambda value: value['edge_id'])
    nodes = []
    for node_id in sorted(reachable):
        node = by_id[node_id]
        nodes.append({
            'node_id': node_id,
            'minimum_hops': distances[node_id],
            'impact_status': node['impact_status'],
            'direct_impact_ids': node['direct_impact_ids'],
            'transitive_impact_ids': node['transitive_impact_ids'],
        })
    cycles = _cyclic_components(reachable, edges)
    payload = {
        'impact_report_version': IMPACT_REPORT_VERSION,
        'projection_hash': projection.content_hash,
        'seed_node_ids': seeds,
        'nodes': nodes,
        'edges': edges,
        'shortest_path_witnesses': [witnesses[node_id]
                                    for node_id in sorted(witnesses)],
        'cycle_components': cycles,
        'summary': {
            'seed_count': len(seeds),
            'reachable_node_count': len(nodes),
            'traversed_edge_count': len(edges),
            'cycle_component_count': len(cycles),
            'shortest_path_witness_count': len(witnesses),
            'maximum_minimum_hops': max(distances.values()),
        },
        'coverage': {
            'scope': 'validated_explicit_projection_only',
            'source_warning_count': len(source['coverage']['warnings']),
            'cycle_safe_traversal': True,
            'shortest_path_witness_basis': (
                'first_by_sorted_seed_then_declared_edge_id'
            ),
            'undeclared_dependencies_inferred': False,
            'no_recorded_impact_is_not_safe': True,
        },
        'authority': {
            'read_only': True,
            'external_actions': False,
            'repair_authority': False,
            'deployment_authority': False,
        },
    }
    return DependencyImpactTraversalReport(canonical_json(payload))
