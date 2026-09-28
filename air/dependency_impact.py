"""Explicit dependency registrations and deterministic, conservative impact evidence.

Registries are immutable sets for one snapshot. They are declarations by trusted
integrators, never claims that all runtime dependencies have been discovered.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Iterable
from uuid import UUID

from air.change_evidence import _snapshot, load_change_evidence
from air.change_intelligence import ChangeSet, METHODS, _Document, _parameters, compare_openapi
from air.postgres import EvidenceTransaction, MAX_PAYLOAD_BYTES, canonical_json

IMPACT_VERSION = 'air-dependency-impact-v1'
WORKFLOW_VERSION = 'air-dependency-impact-v2'
MAX_WORKFLOW_EDGES = 2000
MAX_WORKFLOW_HOPS = 32
MAX_TRAVERSAL_STEPS = 100_000
MAX_WORKFLOW_OUTPUT_BYTES = MAX_PAYLOAD_BYTES
MAX_DEPENDENCIES = 1000
MAX_COMPARISONS = 200_000
MAX_IMPACTS = 5000


class ImpactError(ValueError):
    """Fixed codes only; never include contract content in errors."""


def _digest(value):
    return sha256(canonical_json(value).encode()).hexdigest()


def _tokens(location):
    if not isinstance(location, str) or len(location) > 2048 or any(ord(c) < 32 for c in location):
        raise ImpactError('invalid_contract_location')
    if location == '':
        return ()
    if not location.startswith('/') or re.search(r'~(?![01])', location):
        raise ImpactError('invalid_contract_location')
    return tuple(t.replace('~1', '/').replace('~0', '~') for t in location[1:].split('/'))


@dataclass(frozen=True)
class Dependency:
    integration_id: str
    mapping_id: str
    location: str
    operation: str | None = None
    integration_kind: str = 'integration'

    def __post_init__(self):
        if any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', v)
               for v in (self.integration_id, self.mapping_id)):
            raise ImpactError('invalid_dependency_identity')
        if self.integration_kind not in ('integration', 'adapter', 'workflow'):
            raise ImpactError('invalid_integration_kind')
        tokens = _tokens(self.location)
        if self.operation is not None:
            if not isinstance(self.operation, str) or len(self.operation) > 2048:
                raise ImpactError('invalid_dependency_operation')
            method, sep, path = self.operation.partition(' ')
            if not sep or method.lower() not in METHODS or method != method.upper() or not path.startswith('/'):
                raise ImpactError('invalid_dependency_operation')
            if any(ord(c) < 32 for c in self.operation):
                raise ImpactError('invalid_dependency_operation')
            if len(tokens) >= 2 and tokens[0] == 'paths' and tokens[1] != path:
                raise ImpactError('conflicting_dependency_operation')
            if len(tokens) >= 3 and tokens[0] == 'paths' and tokens[2] in METHODS and tokens[2] != method.lower():
                raise ImpactError('conflicting_dependency_operation')


def _dependencies(values: Iterable[Dependency]) -> list[dict]:
    result = {}
    for index, value in enumerate(values):
        if index >= MAX_DEPENDENCIES:
            raise ImpactError('dependency_limit')
        if not isinstance(value, Dependency):
            raise ImpactError('invalid_dependency')
        payload = asdict(value)
        result[canonical_json(payload)] = payload
    return [result[key] for key in sorted(result)]



@dataclass(frozen=True)
class WorkflowEdge:
    """An explicit upstream-to-downstream relationship within one registry.

    Both endpoints must be existing Dependency values in that registry. There
    are no external registry IDs or implicit edges between similarly named nodes.
    """
    upstream: Dependency
    downstream: Dependency
    relation: str = 'consumes_output'

    def __post_init__(self):
        if not isinstance(self.upstream, Dependency) or not isinstance(self.downstream, Dependency):
            raise ImpactError('invalid_workflow_endpoint')
        if self.relation != 'consumes_output':
            raise ImpactError('unsupported_workflow_relation')


def _edge(value):
    try:
        if not isinstance(value, dict) or set(value) != {'upstream', 'downstream', 'relation'}:
            raise ImpactError('invalid_workflow_edge')
        return WorkflowEdge(Dependency(**value['upstream']), Dependency(**value['downstream']), value['relation'])
    except (KeyError, TypeError):
        raise ImpactError('invalid_workflow_edge') from None


def _workflow_edges(values, registrations):
    registered = {canonical_json(d) for d in registrations}
    normalized = {}
    for index, edge in enumerate(values):
        if index >= MAX_WORKFLOW_EDGES:
            raise ImpactError('workflow_edge_limit')
        if not isinstance(edge, WorkflowEdge):
            raise ImpactError('invalid_workflow_edge')
        value = asdict(edge)
        if any(canonical_json(value[key]) not in registered for key in ('upstream', 'downstream')):
            raise ImpactError('workflow_endpoint_not_registered')
        normalized[canonical_json(value)] = value
    return [normalized[key] for key in sorted(normalized)]


def _propagate(report, registrations, edges):
    """Multi-source BFS: one canonical shortest explanation per change/node.

    Seed IDs and outgoing edge IDs are sorted before traversal. Seen-on-enqueue
    prevents cycles and path explosion. Bounds abort the entire analysis instead
    of publishing an apparently complete truncated result.
    """
    edge_hash = _digest({'workflow_edges': edges})
    output_bytes = len(canonical_json(report).encode())
    nodes = {_digest(d): d for d in registrations}
    adjacency = {node: [] for node in nodes}
    for edge in edges:
        adjacency[_digest(edge['upstream'])].append((_digest(edge), edge))
    for outgoing in adjacency.values():
        outgoing.sort(key=lambda item: item[0])
    seeds = {}
    for impact in report['impacts']:
        seeds.setdefault(impact['change_id'], []).append(impact)
    downstream, steps = [], 0
    for change_id in sorted(seeds):
        queue, seen = deque(), set()
        for impact in sorted(seeds[change_id], key=lambda item: (_digest(item['dependency']), item['impact_id'])):
            node = _digest(impact['dependency'])
            if node not in seen:
                seen.add(node)
                queue.append((node, impact, [node], []))
        while queue:
            node, root, node_path, edge_path = queue.popleft()
            for edge_id, edge in adjacency[node]:
                steps += 1
                if steps > MAX_TRAVERSAL_STEPS:
                    raise ImpactError('workflow_traversal_limit')
                target = _digest(edge['downstream'])
                if target in seen:
                    continue
                if len(edge_path) >= MAX_WORKFLOW_HOPS:
                    raise ImpactError('workflow_depth_limit')
                seen.add(target)
                next_nodes = node_path + [target]
                next_edges = edge_path + [{'edge_id': edge_id, **edge}]
                impact = {'change_id': change_id, 'change_location': root['change_location'],
                    'change_type': root['change_type'], 'classification': root['classification'],
                    'dependency': nodes[target], 'dependency_id': target,
                    'root_impact_id': root['impact_id'], 'root_dependency_id': node_path[0],
                    'match': 'TRANSITIVE_REVIEW',
                    'reason': 'Registered consumes_output edges connect this dependency to an impacted dependency; downstream behavior requires review.',
                    'hops': len(next_edges), 'path': {'nodes': next_nodes, 'edges': next_edges}}
                result = {'impact_id': _digest(impact), **impact}
                output_bytes += len(canonical_json(result).encode()) + 1
                if output_bytes > MAX_WORKFLOW_OUTPUT_BYTES:
                    raise ImpactError('workflow_evidence_size_limit')
                downstream.append(result)
                if len(report['impacts']) + len(downstream) > MAX_IMPACTS:
                    raise ImpactError('impact_result_limit')
                queue.append((target, root, next_nodes, next_edges))
    downstream.sort(key=lambda item: (item['change_id'], item['dependency_id']))
    return {**report, 'impact_version': WORKFLOW_VERSION, 'downstream_impacts': downstream,
        'workflow_edges_hash': edge_hash,
        'traversal': {'algorithm': 'sorted_multi_source_bfs_v1', 'max_hops': MAX_WORKFLOW_HOPS,
                      'max_steps': MAX_TRAVERSAL_STEPS, 'examined_edges': steps,
                      'path_policy': 'one_canonical_shortest_path_per_change_and_dependency'}}


@dataclass(frozen=True)
class ImpactReport:
    payload_json: str

    def to_dict(self):
        return json.loads(self.payload_json)

    @property
    def content_hash(self):
        return sha256(self.payload_json.encode()).hexdigest()


def analyze_changes(changes: ChangeSet, dependencies: Iterable[Dependency],
                    *, workflow_edges: Iterable[WorkflowEdge] = ()) -> ImpactReport:
    """Match consequential changes to declared dependencies, with conservative fallbacks.

    Overlapping pointers are direct evidence. Other changes to a registered
    operation and global authentication changes are potential impact requiring
    review. Empty results never prove an integration safe or a registry complete.
    """
    registrations = _dependencies(dependencies)
    edges = _workflow_edges(workflow_edges, registrations)
    if len(changes.changes) * len(registrations) > MAX_COMPARISONS:
        raise ImpactError('impact_comparison_limit')
    impacts = []
    for change in changes.changes:
        if change.classification == 'NON_BREAKING':
            continue
        changed = _tokens(change.location)
        for dependency in registrations:
            selected = _tokens(dependency['location'])
            operation = dependency['operation']
            if operation is None and len(selected) >= 3 and selected[0] == 'paths' and selected[2] in METHODS:
                operation = selected[2].upper() + ' ' + selected[1]
            if operation is not None and change.operation is not None and operation != change.operation:
                continue
            overlap = changed[:len(selected)] == selected or selected[:len(changed)] == changed
            scope = changed[:-2] if change.change_type.startswith('REQUIRED_PROPERTY_') else changed[:-1]
            schema_overlap = (change.context in ('request', 'response', 'neutral') and
                change.change_type not in ('PROPERTY_ADDED', 'PROPERTY_REMOVED') and
                (scope[:len(selected)] == selected or selected[:len(scope)] == scope))
            if overlap:
                match, reason = 'LOCATION_OVERLAP', 'Changed contract location overlaps the declared dependency.'
            elif schema_overlap:
                match, reason = 'SCHEMA_REVIEW', 'An enclosing schema or parameter constraint changed; dependent fields require review.'
            elif change.operation and operation == change.operation:
                match, reason = 'OPERATION_REVIEW', 'The registered operation changed; indirect mapping effects require review.'
            elif change.classification == 'SECURITY_RELEVANT' and change.operation is None:
                match, reason = 'GLOBAL_SECURITY_REVIEW', 'Global authentication changed; registered consumers require security review.'
            else:
                continue
            impact = {'change_id': change.change_id, 'change_location': change.location,
                      'change_type': change.change_type, 'classification': change.classification,
                      'dependency': dependency, 'match': match, 'reason': reason}
            impacts.append({'impact_id': _digest(impact), **impact})
            if len(impacts) > MAX_IMPACTS:
                raise ImpactError('impact_result_limit')
    impacts.sort(key=lambda i: (i['dependency']['integration_id'], i['dependency']['mapping_id'],
                               i['change_location'], i['impact_id']))
    report = {'impact_version': IMPACT_VERSION,
        'change_set_hash': changes.content_hash, 'dependencies_hash': _digest({'dependencies': registrations}),
        'impacts': impacts, 'coverage_warnings': changes.to_dict()['coverage_warnings'],
        'scope': 'explicit_registry_only', 'review_required': bool(impacts) or changes.review_required}
    if edges:
        report = _propagate(report, registrations, edges)
    return ImpactReport(canonical_json(report))


def _validate_locations(contract, dependencies):
    # Use exactly the detector's bounded reference expansion and parameter identities.
    doc = _Document(contract, 'previous').value
    for path, item in doc['paths'].items():
        inherited = _parameters(item.get('parameters', []))
        for method in METHODS & item.keys():
            op = item[method]
            merged = {**inherited, **_parameters(op.get('parameters', []))}
            op['parameters'] = {}
            for (where, name), parameter in merged.items():
                op['parameters'].setdefault(where, {})[name] = parameter
            op['security'] = op.get('security', doc.get('security', []))
    for dependency in dependencies:
        operation = dependency['operation']
        if operation:
            method, path = operation.split(' ', 1)
            if method.lower() not in doc['paths'].get(path, {}):
                raise ImpactError('dependency_operation_not_found')
        value = doc
        try:
            for token in _tokens(dependency['location']):
                if isinstance(value, list):
                    if not re.fullmatch(r'0|[1-9][0-9]*', token):
                        raise ValueError()
                    value = value[int(token)]
                else:
                    value = value[token]
        except (KeyError, IndexError, TypeError, ValueError):
            raise ImpactError('dependency_location_not_found') from None


def _registry_payload(transaction, snapshot_id, dependencies, workflow_edges=()):
    snapshot, contract = _snapshot(transaction, snapshot_id)
    normalized = _dependencies(dependencies)
    _validate_locations(contract, normalized)
    edges = _workflow_edges(workflow_edges, normalized)
    return {'tenant_id': str(transaction.tenant_id),
            'registry_version': WORKFLOW_VERSION if edges else IMPACT_VERSION,
            'snapshot': snapshot, 'dependencies': normalized,
            **({'workflow_edges': edges} if edges else {})}


def register_dependencies(transaction: EvidenceTransaction, snapshot_id: str | UUID,
                          dependencies: Iterable[Dependency],
                          *, workflow_edges: Iterable[WorkflowEdge] = ()) -> dict:
    """Persist an immutable, content-addressed registry revision for one snapshot."""
    payload = _registry_payload(transaction, snapshot_id, dependencies, workflow_edges)
    return transaction.put('contract_dependency_registry', _digest(payload), payload)


def _artifact(transaction, identity, kind):
    try:
        record = transaction.get_by_id(identity, kind=kind)
    except (ValueError, TypeError):
        raise ImpactError('impact_evidence_not_found_or_not_authorized') from None
    if record is None or record['tenant_id'] != transaction.tenant_id:
        raise ImpactError('impact_evidence_not_found_or_not_authorized')
    return record


def load_registry(transaction: EvidenceTransaction, identity: str | UUID) -> dict:
    record = _artifact(transaction, identity, 'contract_dependency_registry')
    try:
        payload = json.loads(record['payload'])
        if payload['registry_version'] not in (IMPACT_VERSION, WORKFLOW_VERSION):
            raise ImpactError('unsupported_registry_version')
        actual = _registry_payload(transaction, payload['snapshot']['artifact_id'],
                                   [Dependency(**d) for d in payload['dependencies']],
                                   [_edge(e) for e in payload.get('workflow_edges', [])])
        if canonical_json(actual) != record['payload'] or _digest(actual) != record['content_hash']:
            raise ImpactError('registry_integrity_failure')
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ImpactError('invalid_registry_evidence') from None
    return record


def _impact_payload(transaction, change_id, registry_id):
    change = load_change_evidence(transaction, change_id)
    registry = load_registry(transaction, registry_id)
    change_payload, registered = json.loads(change['payload']), json.loads(registry['payload'])
    if registered['snapshot'] != change_payload['previous_snapshot']:
        raise ImpactError('registry_snapshot_mismatch')
    _, previous = _snapshot(transaction, change_payload['previous_snapshot']['artifact_id'])
    _, current = _snapshot(transaction, change_payload['new_snapshot']['artifact_id'])
    report = analyze_changes(compare_openapi(previous, current),
                             [Dependency(**d) for d in registered['dependencies']],
                             workflow_edges=[_edge(e) for e in registered.get('workflow_edges', [])])
    return {'tenant_id': str(transaction.tenant_id), 'impact_version': report.to_dict()['impact_version'],
        'change_evidence': {'artifact_id': str(change['artifact_id']), 'artifact_hash': change['content_hash']},
        'registry': {'artifact_id': str(registry['artifact_id']), 'artifact_hash': registry['content_hash']},
        'impact_hash': report.content_hash, 'analysis': report.to_dict()}


def analyze_and_persist(transaction: EvidenceTransaction, change_id: str | UUID,
                        registry_id: str | UUID) -> dict:
    payload = _impact_payload(transaction, change_id, registry_id)
    return transaction.put('contract_dependency_impact', _digest(payload), payload)


def load_impact(transaction: EvidenceTransaction, identity: str | UUID) -> dict:
    record = _artifact(transaction, identity, 'contract_dependency_impact')
    try:
        payload = json.loads(record['payload'])
        if payload['impact_version'] not in (IMPACT_VERSION, WORKFLOW_VERSION):
            raise ImpactError('unsupported_impact_version')
        actual = _impact_payload(transaction, payload['change_evidence']['artifact_id'],
                                  payload['registry']['artifact_id'])
        if canonical_json(actual) != record['payload'] or _digest(actual) != record['content_hash']:
            raise ImpactError('impact_integrity_failure')
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ImpactError('invalid_impact_evidence') from None
    return record
