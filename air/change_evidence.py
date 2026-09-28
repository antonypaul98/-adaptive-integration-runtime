"""Authenticated, deterministic change evidence over persisted immutable snapshots."""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from air.change_intelligence import DETECTOR_VERSION, compare_openapi
from air.observer import validate_ip, validate_url
from air.postgres import EvidenceTransaction, canonical_json


class EvidenceError(ValueError):
    pass


def _snapshot(transaction: EvidenceTransaction, identity: str | UUID) -> tuple[dict, dict]:
    try:
        artifact = transaction.get_by_id(identity, kind='contract_observation')
    except (ValueError, TypeError):
        raise EvidenceError('snapshot_not_found_or_not_authorized') from None
    if artifact is None or artifact['tenant_id'] != transaction.tenant_id:
        raise EvidenceError('snapshot_not_found_or_not_authorized')
    try:
        payload = json.loads(artifact['payload'])
        contract = payload['contract']
        if sha256(artifact['payload'].encode()).hexdigest() != artifact['content_hash']:
            raise ValueError()
        if sha256(canonical_json(contract).encode()).hexdigest() != payload['content_hash']:
            raise ValueError()
        if payload['normalization'] != 'air-json-redacted-v1':
            raise ValueError()
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', payload['source_id']):
            raise ValueError()
        validate_url(payload['origin'])
        origin = urlsplit(payload['origin'])
        if origin.path not in ('', '/') or origin.query or origin.fragment:
            raise ValueError()
        validate_ip(payload['resolved_ip'])
        if datetime.fromisoformat(payload['observed_at']).utcoffset() is None:
            raise ValueError()
        if type(payload['redirects']) is not int or not 0 <= payload['redirects'] <= 3:
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise EvidenceError('invalid_snapshot_integrity_or_provenance') from None
    reference = {'artifact_id': str(artifact['artifact_id']),
        'artifact_hash': artifact['content_hash'], 'contract_hash': payload['content_hash'],
        **{key: payload[key] for key in ('source_id', 'origin', 'observed_at',
                                       'resolved_ip', 'redirects', 'normalization')}}
    return reference, contract


def _payload(transaction, previous_id, new_id):
    previous, old = _snapshot(transaction, previous_id)
    current, new = _snapshot(transaction, new_id)
    if any(previous[key] != current[key] for key in ('source_id', 'origin', 'normalization')):
        raise EvidenceError('incomparable_snapshot_sources')
    comparison = compare_openapi(old, new)
    result = {'tenant_id': str(transaction.tenant_id),
        'previous_snapshot': previous, 'new_snapshot': current,
        'detector_version': DETECTOR_VERSION, 'change_set_hash': comparison.content_hash,
        'review_required': comparison.review_required, 'comparison': comparison.to_dict()}
    # Fail before writing anything if the complete immutable record exceeds storage bounds.
    canonical_json(result)
    return result


def detect_and_persist(transaction: EvidenceTransaction, previous_id: str | UUID,
                       new_id: str | UUID) -> dict[str, Any]:
    """Compare only authorized stored snapshots and atomically persist one change set.

    The ordered snapshot pair and detector version form the idempotency key.
    The database's artifact created_at is the detection timestamp, so timestamps
    never perturb normalized change hashes or cause retried writes to conflict.
    """
    payload = _payload(transaction, previous_id, new_id)
    identity = canonical_json({'previous': payload['previous_snapshot']['artifact_id'],
        'new': payload['new_snapshot']['artifact_id'], 'version': DETECTOR_VERSION})
    key = sha256(identity.encode()).hexdigest()
    return transaction.put('contract_change_set', key, payload)


def load_change_evidence(transaction: EvidenceTransaction, artifact_id: str | UUID) -> dict[str, Any]:
    """Reload, authorize references and recompute the deterministic evidence as an integrity check."""
    try:
        artifact = transaction.get_by_id(artifact_id, kind='contract_change_set')
    except (ValueError, TypeError):
        raise EvidenceError('change_evidence_not_found_or_not_authorized') from None
    if artifact is None or artifact['tenant_id'] != transaction.tenant_id:
        raise EvidenceError('change_evidence_not_found_or_not_authorized')
    try:
        stored = json.loads(artifact['payload'])
        if stored['detector_version'] != DETECTOR_VERSION:
            raise EvidenceError('unsupported_detector_version')
        actual = _payload(transaction, stored['previous_snapshot']['artifact_id'],
                          stored['new_snapshot']['artifact_id'])
        if (canonical_json(actual) != artifact['payload'] or
                sha256(artifact['payload'].encode()).hexdigest() != artifact['content_hash']):
            raise EvidenceError('change_evidence_integrity_failure')
    except (KeyError, TypeError, json.JSONDecodeError):
        raise EvidenceError('invalid_change_evidence') from None
    return artifact
