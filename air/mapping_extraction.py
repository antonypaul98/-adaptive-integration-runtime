"""Deterministic extraction from registered declarative adapter mappings.

This describes bindings, never executes transformations, discovers runtime code,
fetches contracts, or infers ownership. All authoritative inputs are immutable
artifacts loaded through the authenticated tenant transaction.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from uuid import UUID

from air.change_evidence import _snapshot
from air.change_intelligence import METHODS, pointer
from air.dependency_impact import (Dependency, _dependencies, _tokens, _validate_locations,
    load_registry, register_dependencies)
from air.postgres import EvidenceTransaction, canonical_json, tenant_uuid

MAPPING_VERSION = 'air-adapter-mapping-v1'
EXTRACTOR_VERSION = 'air-mapping-extractor-v1'
MAX_MAPPINGS = 200
MAX_BINDINGS = 500
MAX_MANIFESTS = 32


class ExtractionError(ValueError):
    """Fixed diagnostics without customer mapping content."""


def _hash(value):
    return sha256(canonical_json(value).encode()).hexdigest()


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ExtractionError('malformed_or_unsupported_mapping')


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value):
        raise ExtractionError('invalid_mapping_identity')
    return value


def _uuid(value):
    try:
        return str(tenant_uuid(value))
    except (ValueError, TypeError, AttributeError):
        raise ExtractionError('invalid_mapping_ownership_or_snapshot') from None


def _location(value):
    try:
        _tokens(value)
    except ValueError:
        raise ExtractionError('invalid_mapping_pointer') from None
    return value


def _unique(records, key):
    result = {}
    for record in records:
        identity = record[key]
        if identity in result and result[identity] != record:
            raise ExtractionError('ambiguous_mapping_identity')
        result[identity] = record
    return [result[key] for key in sorted(result)]


def _contract_binding(value):
    if not isinstance(value, dict):
        raise ExtractionError('malformed_contract_binding')
    kind = value.get('kind')
    if kind == 'parameter':
        _keys(value, ('kind', 'in', 'name'))
        if value['in'] not in ('path', 'query', 'header', 'cookie'):
            raise ExtractionError('unsupported_parameter_location')
        name = value['name']
        if not isinstance(name, str) or not 1 <= len(name) <= 256 or any(ord(c) < 32 for c in name):
            raise ExtractionError('invalid_parameter_name')
        return {**value, 'name': name.lower() if value['in'] == 'header' else name}
    if kind not in ('request_body', 'response_body'):
        raise ExtractionError('unsupported_contract_binding')
    keys = ('kind', 'media_type', 'field') + (('status',) if kind == 'response_body' else ())
    _keys(value, keys)
    media = value['media_type']
    if not isinstance(media, str) or len(media) > 128 or not re.fullmatch(r'[A-Za-z0-9!#$&^_.+*-]+/[A-Za-z0-9!#$&^_.+*-]+', media):
        raise ExtractionError('unsupported_media_type')
    if kind == 'response_body' and (not isinstance(value['status'], str) or
            not re.fullmatch(r'[1-5](?:[0-9]{2}|XX)|default', value['status'])):
        raise ExtractionError('invalid_response_status')
    _location(value['field'])
    return dict(value)


def normalize_mapping(manifest: dict, authenticated_tenant: str | UUID) -> dict:
    """Validate ownership and normalize the supported mapping grammar, without I/O."""
    _keys(manifest, ('mapping_version', 'tenant_id', 'snapshot_id', 'adapter_id', 'mappings'))
    if _uuid(manifest['tenant_id']) != _uuid(authenticated_tenant):
        raise ExtractionError('mapping_not_found_or_not_authorized')
    if manifest['mapping_version'] != MAPPING_VERSION:
        raise ExtractionError('unsupported_mapping_version')
    try:
        canonical_json(manifest)  # Reject excessive size, non-JSON values and nonfinite numbers.
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ExtractionError('invalid_mapping_document') from None
    mappings = manifest['mappings']
    if not isinstance(mappings, list) or not 1 <= len(mappings) <= MAX_MAPPINGS:
        raise ExtractionError('mapping_count_limit')
    normalized, count = [], 0
    for mapping in mappings:
        _keys(mapping, ('mapping_id', 'method', 'path', 'bindings'))
        mapping_id = _identity(mapping['mapping_id'])
        method, path = mapping['method'], mapping['path']
        if not isinstance(method, str) or method.lower() not in METHODS:
            raise ExtractionError('unsupported_mapping_operation')
        if not isinstance(path, str) or not path.startswith('/') or len(path) > 1024 or any(ord(c) < 32 for c in path):
            raise ExtractionError('invalid_mapping_path')
        bindings = mapping['bindings']
        if not isinstance(bindings, list):
            raise ExtractionError('malformed_mapping_bindings')
        count += len(bindings)
        if count > MAX_BINDINGS:
            raise ExtractionError('binding_count_limit')
        fields = []
        for binding in bindings:
            _keys(binding, ('binding_id', 'contract', 'adapter_field', 'transform'))
            if binding['transform'] != 'identity':
                raise ExtractionError('unsupported_mapping_transform')
            fields.append({'binding_id': _identity(binding['binding_id']),
                'contract': _contract_binding(binding['contract']),
                'adapter_field': _location(binding['adapter_field']), 'transform': 'identity'})
        normalized.append({'mapping_id': mapping_id, 'method': method.upper(), 'path': path,
                           'bindings': _unique(fields, 'binding_id')})
    return {'mapping_version': MAPPING_VERSION, 'tenant_id': _uuid(authenticated_tenant),
            'snapshot_id': _uuid(manifest['snapshot_id']), 'adapter_id': _identity(manifest['adapter_id']),
            'mappings': _unique(normalized, 'mapping_id')}


@dataclass(frozen=True)
class ExtractedDependencies:
    payload_json: str

    def to_dict(self):
        return json.loads(self.payload_json)

    @property
    def content_hash(self):
        return sha256(self.payload_json.encode()).hexdigest()

    @property
    def dependencies(self):
        return tuple(Dependency(**d) for d in self.to_dict()['dependencies'])


def extract_dependencies(manifest: dict, authenticated_tenant: str | UUID) -> ExtractedDependencies:
    """Derive operation and schema/parameter dependencies from evidenced bindings.

    Body fields are object-property JSON pointers; array traversal and dynamic
    transformations are unsupported. Persisted registration validates every
    generated contract location against the actual authorized snapshot.
    """
    manifest = normalize_mapping(manifest, authenticated_tenant)
    dependencies, provenance = [], {}
    def add(mapping, location, source, reason):
        dependency = Dependency(manifest['adapter_id'], mapping['mapping_id'], location,
                                mapping['method'] + ' ' + mapping['path'], 'adapter')
        value = asdict(dependency)
        identity = _hash(value)
        dependencies.append(dependency)
        record = provenance.setdefault(identity, {'dependency_hash': identity,
            'dependency': value, 'sources': []})
        record['sources'].append({'mapping_id': mapping['mapping_id'],
                                  'manifest_location': source, 'reason': reason})
    for i, mapping in enumerate(manifest['mappings']):
        operation = pointer(pointer('/paths', mapping['path']), mapping['method'].lower())
        add(mapping, operation, f'/mappings/{i}', 'registered_http_operation')
        for j, binding in enumerate(mapping['bindings']):
            field = binding['contract']
            if field['kind'] == 'parameter':
                location = pointer(pointer(operation + '/parameters', field['in']), field['name'])
            else:
                location = (operation + '/requestBody' if field['kind'] == 'request_body' else
                            pointer(operation + '/responses', field['status']))
                location = pointer(location + '/content', field['media_type']) + '/schema'
                for token in _tokens(field['field']):
                    location = pointer(location + '/properties', token)
            add(mapping, location, f'/mappings/{i}/bindings/{j}', 'contract_' + field['kind'] + '_binding')
    normalized = _dependencies(dependencies)
    return ExtractedDependencies(canonical_json({'extractor_version': EXTRACTOR_VERSION,
        'manifest_hash': _hash(manifest), 'dependencies': normalized,
        'provenance': [provenance[key] for key in sorted(provenance)]}))


def _mapping_payload(transaction, manifest):
    normalized = normalize_mapping(manifest, transaction.tenant_id)
    snapshot, contract = _snapshot(transaction, normalized['snapshot_id'])
    extracted = extract_dependencies(normalized, transaction.tenant_id)
    _validate_locations(contract, extracted.to_dict()['dependencies'])
    return {'tenant_id': str(transaction.tenant_id), 'snapshot': snapshot, 'manifest': normalized}


def register_adapter_mapping(transaction: EvidenceTransaction, manifest: dict) -> dict:
    """Register one immutable, content-addressed adapter mapping revision."""
    payload = _mapping_payload(transaction, manifest)
    return transaction.put('registered_adapter_mapping', _hash(payload), payload)


def _artifact(transaction, identity, kind):
    try:
        record = transaction.get_by_id(identity, kind=kind)
    except (ValueError, TypeError):
        raise ExtractionError('mapping_not_found_or_not_authorized') from None
    if record is None or record['tenant_id'] != transaction.tenant_id:
        raise ExtractionError('mapping_not_found_or_not_authorized')
    return record


def load_adapter_mapping(transaction: EvidenceTransaction, identity: str | UUID) -> dict:
    record = _artifact(transaction, identity, 'registered_adapter_mapping')
    try:
        payload = json.loads(record['payload'])
        actual = _mapping_payload(transaction, payload['manifest'])
        if canonical_json(actual) != record['payload'] or _hash(actual) != record['content_hash']:
            raise ExtractionError('mapping_integrity_failure')
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ExtractionError('invalid_mapping_evidence') from None
    return record


def _reference(record):
    return {'artifact_id': str(record['artifact_id']), 'artifact_hash': record['content_hash']}


def _inputs(transaction, mapping_ids, explicit_registry_id):
    identities = set()
    for index, identity in enumerate(mapping_ids):
        if index >= MAX_MANIFESTS:
            raise ExtractionError('mapping_manifest_limit')
        identities.add(_uuid(identity))
    if not identities:
        raise ExtractionError('missing_registered_mappings')
    references, dependencies, provenance, adapters = [], [], [], set()
    snapshot = None
    for identity in sorted(identities):
        record = load_adapter_mapping(transaction, identity)
        payload = json.loads(record['payload'])
        if snapshot is not None and snapshot != payload['snapshot']:
            raise ExtractionError('mapping_snapshot_mismatch')
        snapshot = payload['snapshot']
        manifest = payload['manifest']
        if manifest['adapter_id'] in adapters:
            raise ExtractionError('ambiguous_adapter_revision')
        adapters.add(manifest['adapter_id'])
        reference = _reference(record)
        references.append(reference)
        extraction = extract_dependencies(manifest, transaction.tenant_id)
        dependencies.extend(extraction.dependencies)
        for item in extraction.to_dict()['provenance']:
            provenance.append({**item, 'mapping_artifact': reference})
    base = None
    if explicit_registry_id is not None:
        record = load_registry(transaction, explicit_registry_id)
        base = _reference(record)
        payload = json.loads(record['payload'])
        if payload['snapshot'] != snapshot:
            raise ExtractionError('mapping_registry_snapshot_mismatch')
        dependencies.extend(Dependency(**d) for d in payload['dependencies'])
    normalized = _dependencies(dependencies)
    return snapshot, normalized, {'extractor_version': EXTRACTOR_VERSION, 'mappings': references,
        'explicit_registry': base, 'provenance': sorted(provenance, key=canonical_json)}


def _extraction_payload(transaction, registry, snapshot, sources):
    return {'tenant_id': str(transaction.tenant_id), 'snapshot': snapshot,
            'registry': _reference(registry), **sources}


def extract_registered_dependencies(transaction: EvidenceTransaction, mapping_ids,
                                    *, explicit_registry_id: str | UUID | None = None) -> dict:
    """Atomically persist the EXISTING registry plus immutable extraction provenance.

    This savepoint prevents an orphan registry even when callers catch an error
    inside their outer transaction. Authoritative extraction never trusts caller
    dictionaries; it reloads the selected registered artifacts through RLS.
    """
    snapshot, dependencies, sources = _inputs(transaction, mapping_ids, explicit_registry_id)
    with transaction._connection.transaction():
        registry = register_dependencies(transaction, snapshot['artifact_id'],
                                         [Dependency(**d) for d in dependencies])
        payload = _extraction_payload(transaction, registry, snapshot, sources)
        extraction = transaction.put('adapter_dependency_extraction', _hash(payload), payload)
    return {'registry': registry, 'extraction': extraction}


def load_extraction(transaction: EvidenceTransaction, identity: str | UUID) -> dict:
    record = _artifact(transaction, identity, 'adapter_dependency_extraction')
    try:
        payload = json.loads(record['payload'])
        if payload['extractor_version'] != EXTRACTOR_VERSION:
            raise ExtractionError('unsupported_extractor_version')
        base = payload['explicit_registry']
        snapshot, dependencies, sources = _inputs(transaction,
            [ref['artifact_id'] for ref in payload['mappings']], base['artifact_id'] if base else None)
        registry = load_registry(transaction, payload['registry']['artifact_id'])
        registered = json.loads(registry['payload'])
        if registered['snapshot'] != snapshot or registered['dependencies'] != dependencies:
            raise ExtractionError('extraction_registry_mismatch')
        actual = _extraction_payload(transaction, registry, snapshot, sources)
        if canonical_json(actual) != record['payload'] or _hash(actual) != record['content_hash']:
            raise ExtractionError('extraction_integrity_failure')
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ExtractionError('invalid_extraction_evidence') from None
    return record
