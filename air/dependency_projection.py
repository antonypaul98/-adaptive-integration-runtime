"""Deterministic, bounded projections of explicit dependency evidence.

The projection is a review artifact over caller-supplied registry and impact
metadata. It never discovers dependencies, reads production systems, or proves
that an unannotated node is safe.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Iterable
from uuid import UUID

from air.dependency_impact import (
    Dependency,
    ImpactError,
    ImpactReport,
    WorkflowEdge,
    _dependencies,
    _digest,
    _edge,
    _workflow_edges,
    load_impact,
    load_registry,
)
from air.postgres import EvidenceTransaction, canonical_json

PROJECTION_VERSION = 'air-dependency-projection-v1'
PROJECTION_RECORD_VERSION = 'air-dependency-projection-record-v1'
MAX_PROJECTION_IMPACTS = 5000
_HEX_64 = re.compile(r'[0-9a-f]{64}')


class ProjectionError(ValueError):
    """Fixed codes only; never include dependency or contract content."""


@dataclass(frozen=True)
class DependencyProjection:
    payload_json: str

    def to_dict(self):
        return json.loads(self.payload_json)

    @property
    def content_hash(self):
        return sha256(self.payload_json.encode()).hexdigest()


def _impact_index(report, registrations):
    if report is None:
        return {}, {}, [], None
    if not isinstance(report, ImpactReport):
        raise ProjectionError('invalid_impact_report')
    try:
        payload = report.to_dict()
        if payload['dependencies_hash'] != _digest({'dependencies': registrations}):
            raise ProjectionError('projection_registry_mismatch')
        warnings = payload['coverage_warnings']
        if not isinstance(warnings, list) or any(not isinstance(value, str) for value in warnings):
            raise ProjectionError('invalid_impact_report')
        direct, transitive = {}, {}
        registered = {canonical_json(value) for value in registrations}
        groups = (('impacts', direct), ('downstream_impacts', transitive))
        count = 0
        for key, target in groups:
            values = payload.get(key, [])
            if not isinstance(values, list):
                raise ProjectionError('invalid_impact_report')
            for value in values:
                count += 1
                if count > MAX_PROJECTION_IMPACTS:
                    raise ProjectionError('projection_impact_limit')
                if not isinstance(value, dict) or not _HEX_64.fullmatch(value.get('impact_id', '')):
                    raise ProjectionError('invalid_impact_report')
                core = {name: item for name, item in value.items() if name != 'impact_id'}
                if _digest(core) != value['impact_id']:
                    raise ProjectionError('impact_identity_mismatch')
                dependency = value.get('dependency')
                if canonical_json(dependency) not in registered:
                    raise ProjectionError('projection_dependency_not_registered')
                node_id = _digest(dependency)
                target.setdefault(node_id, []).append(value['impact_id'])
        return direct, transitive, sorted(set(warnings)), report.content_hash
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ProjectionError('invalid_impact_report') from None


def project_dependency_graph(
    dependencies: Iterable[Dependency],
    *,
    workflow_edges: Iterable[WorkflowEdge] = (),
    impact_report: ImpactReport | None = None,
) -> DependencyProjection:
    """Create one canonical review projection from explicit, bounded metadata."""
    try:
        registrations = _dependencies(dependencies)
        edges = _workflow_edges(workflow_edges, registrations)
    except ImpactError as exc:
        raise ProjectionError(str(exc)) from None

    direct, transitive, warnings, impact_hash = _impact_index(impact_report, registrations)
    nodes = []
    for dependency in registrations:
        node_id = _digest(dependency)
        direct_ids = sorted(direct.get(node_id, ()))
        transitive_ids = sorted(transitive.get(node_id, ()))
        status = ('direct_review' if direct_ids else
                  'transitive_review' if transitive_ids else
                  'no_recorded_impact')
        nodes.append({
            'node_id': node_id,
            'dependency': dependency,
            'impact_status': status,
            'direct_impact_ids': direct_ids,
            'transitive_impact_ids': transitive_ids,
        })
    nodes.sort(key=lambda value: value['node_id'])

    projected_edges = []
    for edge in edges:
        value = {
            'source_node_id': _digest(edge['upstream']),
            'target_node_id': _digest(edge['downstream']),
            'relation': edge['relation'],
        }
        projected_edges.append({'edge_id': _digest(value), **value})
    projected_edges.sort(key=lambda value: value['edge_id'])

    direct_review_nodes = sum(bool(node['direct_impact_ids']) for node in nodes)
    transitive_review_nodes = sum(bool(node['transitive_impact_ids']) for node in nodes)
    recorded_review_nodes = sum(
        bool(node['direct_impact_ids'] or node['transitive_impact_ids'])
        for node in nodes
    )

    payload = {
        'projection_version': PROJECTION_VERSION,
        'dependencies_hash': _digest({'dependencies': registrations}),
        'workflow_edges_hash': _digest({'workflow_edges': edges}),
        'impact_report_hash': impact_hash,
        'nodes': nodes,
        'edges': projected_edges,
        'impact_summary': {
            'basis': 'recorded_annotations_only',
            'dependency_count': len(nodes),
            'workflow_edge_count': len(projected_edges),
            'recorded_review_node_count': recorded_review_nodes,
            'direct_review_node_count': direct_review_nodes,
            'transitive_review_node_count': transitive_review_nodes,
            'no_recorded_impact_node_count': len(nodes) - recorded_review_nodes,
            'direct_impact_count': sum(len(node['direct_impact_ids']) for node in nodes),
            'transitive_impact_count': sum(
                len(node['transitive_impact_ids']) for node in nodes
            ),
            'counts_are_not_probabilities_or_completeness_claims': True,
        },
        'coverage': {
            'scope': 'explicit_registry_only',
            'warnings': warnings,
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
    return DependencyProjection(canonical_json(payload))


def _persisted_payload(
    transaction: EvidenceTransaction,
    registry_id: str | UUID,
    impact_id: str | UUID | None,
) -> dict:
    try:
        registry = load_registry(transaction, registry_id)
        registry_payload = json.loads(registry['payload'])
        impact = load_impact(transaction, impact_id) if impact_id is not None else None
        impact_payload = json.loads(impact['payload']) if impact is not None else None
        registry_ref = {
            'artifact_id': str(registry['artifact_id']),
            'artifact_hash': registry['content_hash'],
        }
        if impact_payload is not None and impact_payload['registry'] != registry_ref:
            raise ProjectionError('projection_impact_registry_mismatch')
        report = (ImpactReport(canonical_json(impact_payload['analysis']))
                  if impact_payload is not None else None)
        projection = project_dependency_graph(
            [Dependency(**value) for value in registry_payload['dependencies']],
            workflow_edges=[_edge(value)
                            for value in registry_payload.get('workflow_edges', [])],
            impact_report=report,
        )
        return {
            'tenant_id': str(transaction.tenant_id),
            'projection_record_version': PROJECTION_RECORD_VERSION,
            'registry': registry_ref,
            'impact': ({
                'artifact_id': str(impact['artifact_id']),
                'artifact_hash': impact['content_hash'],
            } if impact is not None else None),
            'projection_hash': projection.content_hash,
            'projection_payload': projection.payload_json,
        }
    except ImpactError as exc:
        raise ProjectionError('projection_evidence_not_found_or_invalid') from exc
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, ProjectionError):
            raise
        raise ProjectionError('projection_persistence_rejected') from exc


def project_and_persist(
    transaction: EvidenceTransaction,
    registry_id: str | UUID,
    *,
    impact_id: str | UUID | None = None,
) -> dict:
    """Persist a read-only projection bound to exact tenant-scoped evidence."""
    payload = _persisted_payload(transaction, registry_id, impact_id)
    return transaction.put('dependency_projection', _digest(payload), payload)


def load_projection(transaction: EvidenceTransaction, identity: str | UUID) -> dict:
    """Reload and recompute an immutable projection through tenant RLS."""
    try:
        record = transaction.get_by_id(identity, kind='dependency_projection')
    except (TypeError, ValueError):
        record = None
    if record is None or record['tenant_id'] != transaction.tenant_id:
        raise ProjectionError('projection_not_found_or_not_authorized')
    try:
        payload = json.loads(record['payload'])
        expected = _persisted_payload(
            transaction,
            payload['registry']['artifact_id'],
            payload['impact']['artifact_id'] if payload['impact'] is not None else None,
        )
        expected_json = canonical_json(expected)
        if (record['payload'] != expected_json
                or record['idempotency_key'] != _digest(expected)
                or record['content_hash'] != _digest(expected)):
            raise ProjectionError('invalid_persisted_projection')
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, ProjectionError):
            raise
        raise ProjectionError('invalid_persisted_projection') from exc
    return record
