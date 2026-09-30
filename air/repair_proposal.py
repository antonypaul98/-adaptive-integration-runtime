"""Immutable proposals and human decisions. No execution capability is provided.

Reviewers are administrator-provisioned database identities. Caller-supplied names
or tenant GUCs never confer approval rights. Authorization is an exact-evidence
check for later controlled processing, never deployment permission.
"""
from hashlib import sha256
import json
import re

from .dependency_impact import load_impact
from .postgres import canonical_json, bind_tenant_login, ConfigurationError

VERSION = 'air-repair-proposal-v1'


class ProposalError(ValueError):
    pass


def digest(value):
    return sha256(canonical_json(value).encode()).hexdigest()


def reference(record):
    return {'artifact_id': str(record['artifact_id']), 'artifact_hash': record['content_hash']}


def _text(value, limit=4096):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ProposalError('invalid_description')
    return value


def normalize_description(value):
    """Bounded declarative data; never executable instructions or generated code."""
    keys = {'change_type', 'proposed_state', 'rationale', 'risk', 'generator', 'generator_version'}
    if not isinstance(value, dict) or set(value) != keys:
        raise ProposalError('invalid_description')
    if value['change_type'] not in ('mapping_update', 'operation_update', 'configuration_update'):
        raise ProposalError('unsupported_change_type')
    if value['risk'] not in ('low', 'medium', 'high') or value['generator'] not in ('human', 'deterministic'):
        raise ProposalError('unsupported_provenance')
    _text(value['rationale']); _text(value['generator_version'], 128)
    if not isinstance(value['proposed_state'], dict) or not value['proposed_state']:
        raise ProposalError('invalid_proposed_state')
    encoded = canonical_json(value)
    if len(encoded.encode()) > 65536:
        raise ProposalError('description_limit')
    return json.loads(encoded)


def _get(tx, identity, kind):
    try:
        record = tx.get_by_id(identity, kind=kind)
    except (ValueError, TypeError):
        record = None
    if record is None or record['tenant_id'] != tx.tenant_id:
        raise ProposalError('not_found_or_not_authorized')
    if sha256(record['payload'].encode()).hexdigest() != record['content_hash']:
        raise ProposalError('integrity_failure')
    return record


def _body(tx, impact_id, impact_item_id, description, parent=None):
    impact = load_impact(tx, impact_id)
    evidence = json.loads(impact['payload'])
    analysis = evidence['analysis']
    matches = [r for r in analysis['impacts'] + analysis.get('downstream_impacts', [])
               if r['impact_id'] == impact_item_id]
    if len(matches) != 1:
        raise ProposalError('impact_target_not_found')
    return {'tenant_id': str(tx.tenant_id), 'proposal_version': VERSION,
            'revision': 1 if parent is None else json.loads(parent['payload'])['revision'] + 1,
            'supersedes': None if parent is None else reference(parent),
            'impact': reference(impact), 'change_evidence': evidence['change_evidence'],
            'registry': evidence['registry'], 'impact_item': matches[0],
            'description': normalize_description(description)}


def _load_proposal(tx, identity):
    # Iterative verification bounds revision chains and avoids recursive stack growth.
    record = _get(tx, identity, 'repair_proposal')
    cursor = record
    seen = set()
    for _ in range(100):
        p = json.loads(cursor['payload'])
        if cursor['artifact_id'] in seen:
            raise ProposalError('invalid_revision_chain')
        seen.add(cursor['artifact_id'])
        parent = None if p.get('supersedes') is None else _get(tx, p['supersedes']['artifact_id'], 'repair_proposal')
        expected = _body(tx, p['impact']['artifact_id'], p['impact_item']['impact_id'], p['description'], parent)
        if canonical_json(expected) != cursor['payload'] or digest(expected) != cursor['idempotency_key']:
            raise ProposalError('integrity_failure')
        if parent is None:
            return record
        cursor = parent
    raise ProposalError('revision_limit')


def load_proposal(tx, identity):
    try:
        return _load_proposal(tx, identity)
    except (KeyError, TypeError, json.JSONDecodeError, RecursionError):
        raise ProposalError('malformed_proposal') from None


def _lock(tx, identity):
    tx._connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 714208316))',
                           (str(tx.tenant_id) + ':' + str(identity),))


def _successor(tx, identity):
    return tx._connection.execute("""SELECT artifact_id FROM air.artifacts
        WHERE tenant_id=%s AND kind='repair_proposal'
        AND payload::jsonb#>>'{supersedes,artifact_id}'=%s""", (tx.tenant_id, str(identity))).fetchone()


def create_proposal(tx, impact_id, impact_item_id, description, *, supersedes=None):
    parent = None if supersedes is None else load_proposal(tx, supersedes)
    payload = _body(tx, impact_id, impact_item_id, description, parent)
    if payload['revision'] > 100:
        raise ProposalError('revision_limit')
    key = digest(payload)
    if parent:
        _lock(tx, parent['artifact_id'])
        existing = tx.get('repair_proposal', key)
        if existing:
            return load_proposal(tx, existing['artifact_id'])
        if _successor(tx, parent['artifact_id']):
            raise ProposalError('already_superseded')
        old = json.loads(parent['payload'])
        target = lambda p: (p['impact_item']['dependency']['integration_id'], p['impact_item']['dependency']['mapping_id'])
        if target(old) != target(payload):
            raise ProposalError('revision_target_mismatch')
    return tx.put('repair_proposal', key, payload)


def bind_reviewer(connection, login, tenant, reviewer_ref):
    """Admin-only provisioning. Use a dedicated authenticated human login, not a service login."""
    if not isinstance(reviewer_ref, str) or not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,128}', reviewer_ref):
        raise ConfigurationError('invalid reviewer reference')
    with connection.transaction():
        bind_tenant_login(connection, login, tenant)
        row = connection.execute('SELECT reviewer_ref FROM air_private.proposal_reviewers WHERE login=%s', (login,)).fetchone()
        if row and row[0] != reviewer_ref:
            raise ConfigurationError('reviewer cannot be rebound')
        connection.execute('INSERT INTO air_private.proposal_reviewers(login, reviewer_ref) VALUES (%s,%s) ON CONFLICT DO NOTHING', (login, reviewer_ref))


def decide(tx, proposal_id, *, proposal_hash, revision, decision, confirmed=False):
    if confirmed is not True or decision not in ('APPROVED', 'REJECTED'):
        raise ProposalError('explicit_human_decision_required')
    proposal = load_proposal(tx, proposal_id)
    p = json.loads(proposal['payload'])
    _lock(tx, proposal['artifact_id'])
    if type(revision) is not int or proposal_hash != proposal['content_hash'] or revision != p['revision']:
        raise ProposalError('proposal_binding_mismatch')
    if _successor(tx, proposal['artifact_id']):
        raise ProposalError('superseded')
    reviewer = tx._connection.execute('SELECT air.current_reviewer() AS reviewer').fetchone()['reviewer']
    payload = {'tenant_id': str(tx.tenant_id), 'proposal_version': VERSION,
               'proposal': reference(proposal), 'revision': revision, 'decision': decision,
               'reviewer': reviewer, 'impact': p['impact'], 'change_evidence': p['change_evidence']}
    # One key per proposal: same retry is harmless; conflicting decision/actor fails closed.
    return tx.put('repair_decision', str(proposal['artifact_id']), payload)


def authorization(tx, proposal_id, *, proposal_hash, revision, current_impact_id):
    """Require exact caller-supplied current evidence. No global 'latest' is inferred.

    Returns immutable approval evidence only. Call again at any later stage; this
    return value is not a transferable execution token or deployment authorization.
    """
    proposal = load_proposal(tx, proposal_id)
    p = json.loads(proposal['payload'])
    _lock(tx, proposal['artifact_id'])
    if (type(revision) is not int or p['revision'] != revision or proposal['content_hash'] != proposal_hash
            or p['impact']['artifact_id'] != str(current_impact_id) or _successor(tx, proposal['artifact_id'])):
        raise ProposalError('stale_or_mismatched_authorization')
    record = tx.get('repair_decision', str(proposal['artifact_id']))
    if record is None:
        raise ProposalError('not_authorized')
    d = json.loads(record['payload'])
    if (d.get('decision') != 'APPROVED' or d.get('proposal') != reference(proposal)
            or d.get('revision') != revision or d.get('impact') != p['impact']
            or d.get('change_evidence') != p['change_evidence']
            or d.get('tenant_id') != str(tx.tenant_id)
            or digest(d) != record['content_hash']):
        raise ProposalError('not_authorized')
    return record


def proposal_status(tx, proposal_id):
    """Read lifecycle from append-only evidence; supersession always takes precedence."""
    proposal = load_proposal(tx, proposal_id)
    _lock(tx, proposal['artifact_id'])
    if _successor(tx, proposal['artifact_id']):
        return 'SUPERSEDED'
    record = tx.get('repair_decision', str(proposal['artifact_id']))
    if record is None:
        return 'PROPOSED'
    p, d = json.loads(proposal['payload']), json.loads(record['payload'])
    if (d.get('decision') not in ('APPROVED', 'REJECTED')
            or d.get('proposal') != reference(proposal) or d.get('revision') != p['revision']
            or d.get('tenant_id') != str(tx.tenant_id) or d.get('impact') != p['impact']
            or d.get('change_evidence') != p['change_evidence']
            or digest(d) != record['content_hash']):
        raise ProposalError('invalid_decision')
    return d['decision']
