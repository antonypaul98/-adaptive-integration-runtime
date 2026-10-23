"""Redacted, deterministic presentation data for dependency projections.

This module renders no UI and performs no discovery or action.  It validates an
existing projection before deriving stable review lanes and opaque aliases that
do not expose dependency names, mappings, locations, or operations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re

from air.dependency_impact import (
    MAX_DEPENDENCIES,
    MAX_WORKFLOW_EDGES,
    Dependency,
    _dependencies,
    _digest,
)
from air.dependency_projection import (
    DependencyProjection,
    MAX_PROJECTION_IMPACTS,
    PROJECTION_VERSION,
)
from air.postgres import canonical_json

VISUALIZATION_VERSION = 'air-dependency-visualization-v1'
_HEX_64 = re.compile(r'[0-9a-f]{64}')
_LANES = ('direct_review', 'transitive_review', 'no_recorded_impact')


class VisualizationError(ValueError):
    """Fixed codes only; never include dependency or contract content."""


@dataclass(frozen=True)
class DependencyVisualization:
    payload_json: str

    def to_dict(self):
        return json.loads(self.payload_json)

    @property
    def content_hash(self):
        return sha256(self.payload_json.encode()).hexdigest()


def _hash_list(value, *, code):
    if (not isinstance(value, list) or value != sorted(set(value))
            or any(not isinstance(item, str) or not _HEX_64.fullmatch(item)
                   for item in value)):
        raise VisualizationError(code)
    return value


def _validated_projection(projection):
    if not isinstance(projection, DependencyProjection):
        raise VisualizationError('invalid_dependency_projection')
    try:
        payload = json.loads(projection.payload_json)
        if canonical_json(payload) != projection.payload_json:
            raise VisualizationError('noncanonical_dependency_projection')
        if not isinstance(payload, dict) or set(payload) != {
            'projection_version', 'dependencies_hash', 'workflow_edges_hash',
            'impact_report_hash', 'nodes', 'edges', 'impact_summary',
            'coverage', 'authority',
        }:
            raise VisualizationError('invalid_dependency_projection')
        if payload['projection_version'] != PROJECTION_VERSION:
            raise VisualizationError('unsupported_projection_version')
        if (not _HEX_64.fullmatch(payload['dependencies_hash'])
                or not _HEX_64.fullmatch(payload['workflow_edges_hash'])
                or (payload['impact_report_hash'] is not None
                    and not _HEX_64.fullmatch(payload['impact_report_hash']))):
            raise VisualizationError('invalid_projection_hash')

        raw_nodes = payload['nodes']
        if not isinstance(raw_nodes, list) or len(raw_nodes) > MAX_DEPENDENCIES:
            raise VisualizationError('visualization_node_limit')
        nodes, dependencies, dependency_by_id = [], [], {}
        impact_count = 0
        for node in raw_nodes:
            if not isinstance(node, dict) or set(node) != {
                'node_id', 'dependency', 'impact_status',
                'direct_impact_ids', 'transitive_impact_ids',
            }:
                raise VisualizationError('invalid_projection_node')
            dependency = Dependency(**node['dependency'])
            normalized = asdict(dependency)
            node_id = node['node_id']
            if not isinstance(node_id, str) or _digest(normalized) != node_id:
                raise VisualizationError('projection_node_identity_mismatch')
            if node_id in dependency_by_id:
                raise VisualizationError('duplicate_projection_node')
            direct = _hash_list(
                node['direct_impact_ids'], code='invalid_direct_impact_ids'
            )
            transitive = _hash_list(
                node['transitive_impact_ids'], code='invalid_transitive_impact_ids'
            )
            impact_count += len(direct) + len(transitive)
            if impact_count > MAX_PROJECTION_IMPACTS:
                raise VisualizationError('visualization_impact_limit')
            status = ('direct_review' if direct else
                      'transitive_review' if transitive else
                      'no_recorded_impact')
            if node['impact_status'] != status:
                raise VisualizationError('projection_status_mismatch')
            dependencies.append(dependency)
            dependency_by_id[node_id] = normalized
            nodes.append(node)
        if nodes != sorted(nodes, key=lambda item: item['node_id']):
            raise VisualizationError('noncanonical_projection_nodes')
        registrations = _dependencies(dependencies)
        if _digest({'dependencies': registrations}) != payload['dependencies_hash']:
            raise VisualizationError('projection_dependencies_hash_mismatch')

        raw_edges = payload['edges']
        if not isinstance(raw_edges, list) or len(raw_edges) > MAX_WORKFLOW_EDGES:
            raise VisualizationError('visualization_edge_limit')
        edges, registry_edges, seen_edges = [], [], set()
        for edge in raw_edges:
            if not isinstance(edge, dict) or set(edge) != {
                'edge_id', 'source_node_id', 'target_node_id', 'relation'
            }:
                raise VisualizationError('invalid_projection_edge')
            core = {name: edge[name] for name in (
                'source_node_id', 'target_node_id', 'relation'
            )}
            if (edge['edge_id'] != _digest(core)
                    or edge['edge_id'] in seen_edges):
                raise VisualizationError('projection_edge_identity_mismatch')
            if (edge['source_node_id'] not in dependency_by_id
                    or edge['target_node_id'] not in dependency_by_id):
                raise VisualizationError('projection_edge_endpoint_missing')
            if edge['relation'] != 'consumes_output':
                raise VisualizationError('unsupported_projection_relation')
            seen_edges.add(edge['edge_id'])
            edges.append(edge)
            registry_edges.append({
                'upstream': dependency_by_id[edge['source_node_id']],
                'downstream': dependency_by_id[edge['target_node_id']],
                'relation': edge['relation'],
            })
        if edges != sorted(edges, key=lambda item: item['edge_id']):
            raise VisualizationError('noncanonical_projection_edges')
        registry_edges.sort(key=canonical_json)
        if _digest({'workflow_edges': registry_edges}) != payload['workflow_edges_hash']:
            raise VisualizationError('projection_workflow_hash_mismatch')

        direct_nodes = sum(bool(node['direct_impact_ids']) for node in nodes)
        transitive_nodes = sum(bool(node['transitive_impact_ids']) for node in nodes)
        recorded_nodes = sum(
            bool(node['direct_impact_ids'] or node['transitive_impact_ids'])
            for node in nodes
        )
        expected_summary = {
            'basis': 'recorded_annotations_only',
            'dependency_count': len(nodes),
            'workflow_edge_count': len(edges),
            'recorded_review_node_count': recorded_nodes,
            'direct_review_node_count': direct_nodes,
            'transitive_review_node_count': transitive_nodes,
            'no_recorded_impact_node_count': len(nodes) - recorded_nodes,
            'direct_impact_count': sum(len(node['direct_impact_ids']) for node in nodes),
            'transitive_impact_count': sum(
                len(node['transitive_impact_ids']) for node in nodes
            ),
            'counts_are_not_probabilities_or_completeness_claims': True,
        }
        if payload['impact_summary'] != expected_summary:
            raise VisualizationError('projection_summary_mismatch')
        coverage = payload['coverage']
        if (not isinstance(coverage, dict) or set(coverage) != {
                'scope', 'warnings', 'no_recorded_impact_is_not_safe',
                'dependency_discovery_performed'}
                or coverage['scope'] != 'explicit_registry_only'
                or coverage['no_recorded_impact_is_not_safe'] is not True
                or coverage['dependency_discovery_performed'] is not False
                or not isinstance(coverage['warnings'], list)
                or coverage['warnings'] != sorted(set(coverage['warnings']))
                or any(not isinstance(item, str) for item in coverage['warnings'])):
            raise VisualizationError('invalid_projection_coverage')
        if payload['authority'] != {
            'read_only': True,
            'external_actions': False,
            'repair_authority': False,
            'deployment_authority': False,
        }:
            raise VisualizationError('invalid_projection_authority')
        return payload
    except VisualizationError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise VisualizationError('invalid_dependency_projection') from None


def visualize_dependency_projection(projection) -> DependencyVisualization:
    """Build canonical redacted review lanes from one validated projection."""
    source = _validated_projection(projection)
    aliases = {
        node['node_id']: f'node-{index:04d}'
        for index, node in enumerate(source['nodes'], start=1)
    }
    nodes = [{
        'visual_id': aliases[node['node_id']],
        'node_id': node['node_id'],
        'review_lane': node['impact_status'],
        'direct_impact_count': len(node['direct_impact_ids']),
        'transitive_impact_count': len(node['transitive_impact_ids']),
    } for node in source['nodes']]
    edges = []
    for edge in source['edges']:
        core = {
            'source_visual_id': aliases[edge['source_node_id']],
            'target_visual_id': aliases[edge['target_node_id']],
            'relation': edge['relation'],
        }
        edges.append({'visual_edge_id': _digest(core), **core})
    edges.sort(key=lambda item: item['visual_edge_id'])
    lanes = [{
        'lane': lane,
        'visual_node_ids': [
            node['visual_id'] for node in nodes if node['review_lane'] == lane
        ],
    } for lane in _LANES]
    payload = {
        'visualization_version': VISUALIZATION_VERSION,
        'projection_hash': projection.content_hash,
        'nodes': nodes,
        'edges': edges,
        'review_lanes': lanes,
        'summary': source['impact_summary'],
        'coverage': {
            'scope': 'validated_explicit_projection_only',
            'source_warning_count': len(source['coverage']['warnings']),
            'raw_dependency_metadata_included': False,
            'projection_origin_authenticated': False,
            'no_recorded_impact_is_not_safe': True,
            'dependency_discovery_performed': False,
        },
        'authority': {
            'read_only': True,
            'external_actions': False,
            'repair_authority': False,
            'deployment_authority': False,
        },
    }
    return DependencyVisualization(canonical_json(payload))
