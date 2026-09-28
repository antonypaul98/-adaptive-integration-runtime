from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from air.change_evidence import EvidenceError, detect_and_persist, load_change_evidence
from air.observer import ContractSnapshot
from air.postgres import canonical_json

pytestmark = pytest.mark.postgres


def document(kind='string'):
    return {'openapi': '3.1.0', 'info': {'title': 'Demo', 'version': '1'},
        'paths': {'/items': {'get': {'responses': {'200': {'content': {
            'application/json': {'schema': {'type': kind}}}}}}}}}


def save(tx, kind='string', source='source'):
    value = canonical_json(document(kind))
    snapshot = ContractSnapshot(tx.tenant_id, source, 'https://example.com',
        datetime.now(timezone.utc).isoformat(), '8.8.8.8', 0, value, sha256(value.encode()).hexdigest())
    return snapshot.persist(tx, uuid4().hex)


@pytest.fixture
def pair(database, repos):
    with repos[0].transaction(database['tenants'][0]) as tx:
        return save(tx), save(tx, 'integer')


def test_persistence_reload_idempotence_and_audit(database, repos, pair):
    tenant = database['tenants'][0]
    with repos[0].transaction(tenant) as tx:
        first = detect_and_persist(tx, pair[0]['artifact_id'], pair[1]['artifact_id'])
        again = detect_and_persist(tx, pair[0]['artifact_id'], pair[1]['artifact_id'])
        assert first == again
        payload = json.loads(first['payload'])
        assert payload['tenant_id'] == str(tenant)
        assert payload['comparison']['changes'][0]['classification'] == 'BREAKING'
        assert payload['previous_snapshot']['artifact_id'] == str(pair[0]['artifact_id'])
        assert payload['new_snapshot']['artifact_hash'] == pair[1]['content_hash']
        assert payload['review_required'] is True
        assert first['created_at'].utcoffset() is not None
        assert len([a for a in tx.audit() if a['artifact_id'] == first['artifact_id']]) == 1
    with repos[0].transaction(tenant) as tx:
        assert load_change_evidence(tx, first['artifact_id']) == first


def test_same_snapshot_no_change_evidence(database, repos, pair):
    with repos[0].transaction(database['tenants'][0]) as tx:
        evidence = detect_and_persist(tx, pair[0]['artifact_id'], pair[0]['artifact_id'])
        payload = json.loads(evidence['payload'])
        assert payload['comparison']['changes'] == [] and not payload['review_required']


def test_cross_tenant_reads_and_inputs_fail_closed(database, repos, pair):
    with repos[0].transaction(database['tenants'][0]) as tx:
        evidence = detect_and_persist(tx, pair[0]['artifact_id'], pair[1]['artifact_id'])
    with repos[1].transaction(database['tenants'][1]) as tx:
        own = save(tx)
        for previous, current in [(own, pair[0]), (pair[0], own), pair]:
            with pytest.raises(EvidenceError, match='not_found_or_not_authorized'):
                detect_and_persist(tx, previous['artifact_id'], current['artifact_id'])
        with pytest.raises(EvidenceError, match='not_found_or_not_authorized'):
            load_change_evidence(tx, evidence['artifact_id'])
        assert tx._connection.execute("SELECT * FROM air.artifacts WHERE artifact_id=%s", (evidence['artifact_id'],)).fetchall() == []


@pytest.mark.parametrize('mutation', ['prior_id', 'new_id', 'prior_hash', 'new_hash', 'tenant', 'missing', 'bad_uuid', 'contract_hash'])
def test_database_rejects_forged_snapshot_links(database, repos, pair, mutation):
    with repos[0].transaction(database['tenants'][0]) as tx:
        evidence = detect_and_persist(tx, pair[0]['artifact_id'], pair[1]['artifact_id'])
        payload = json.loads(evidence['payload'])
    with repos[1].transaction(database['tenants'][1]) as tx:
        other = save(tx)
    if mutation == 'prior_id':
        payload['previous_snapshot']['artifact_id'] = str(other['artifact_id'])
    elif mutation == 'new_id':
        payload['new_snapshot']['artifact_id'] = str(other['artifact_id'])
    elif mutation == 'prior_hash':
        payload['previous_snapshot']['artifact_hash'] = '0' * 64
    elif mutation == 'new_hash':
        payload['new_snapshot']['artifact_hash'] = '0' * 64
    elif mutation == 'tenant':
        payload['tenant_id'] = str(database['tenants'][1])
    elif mutation == 'missing':
        del payload['previous_snapshot']
    elif mutation == 'bad_uuid':
        payload['new_snapshot']['artifact_id'] = 'invalid'
    else:
        payload['new_snapshot']['contract_hash'] = '0' * 64
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx.put('contract_change_set', uuid4().hex, payload)


def test_change_evidence_cannot_be_mutated(database, repos, pair):
    with repos[0].transaction(database['tenants'][0]) as tx:
        record = detect_and_persist(tx, pair[0]['artifact_id'], pair[1]['artifact_id'])
    for statement in ('UPDATE air.artifacts SET payload=payload WHERE artifact_id=%s',
                      'DELETE FROM air.artifacts WHERE artifact_id=%s'):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with repos[0].transaction(database['tenants'][0]) as tx:
                tx._connection.execute(statement, (record['artifact_id'],))


def test_failed_detection_rolls_back_other_writes(database, repos, pair):
    key = uuid4().hex
    with pytest.raises(EvidenceError):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx.put('test', key, {})
            detect_and_persist(tx, pair[0]['artifact_id'], uuid4())
    with repos[0].transaction(database['tenants'][0]) as tx:
        assert tx.get('test', key) is None


def test_source_mismatch_rejected(database, repos, pair):
    with repos[0].transaction(database['tenants'][0]) as tx:
        other = save(tx, source='other')
        with pytest.raises(EvidenceError, match='incomparable_snapshot_sources'):
            detect_and_persist(tx, pair[0]['artifact_id'], other['artifact_id'])


@pytest.mark.parametrize('field,value', [('content_hash', 'bad'), ('normalization', 'unknown'),
    ('observed_at', 'yesterday'), ('resolved_ip', '127.0.0.1'), ('origin', 'http://example.com')])
def test_invalid_snapshot_integrity_or_provenance(database, repos, pair, field, value):
    payload = json.loads(pair[0]['payload'])
    payload[field] = value
    with repos[0].transaction(database['tenants'][0]) as tx:
        invalid = tx.put('contract_observation', uuid4().hex, payload)
        with pytest.raises(EvidenceError, match='invalid_snapshot'):
            detect_and_persist(tx, invalid['artifact_id'], pair[1]['artifact_id'])


def test_forged_classification_detected_on_reload(database, repos, pair):
    with repos[0].transaction(database['tenants'][0]) as tx:
        evidence = detect_and_persist(tx, pair[0]['artifact_id'], pair[1]['artifact_id'])
        payload = json.loads(evidence['payload'])
        payload['comparison']['changes'][0]['classification'] = 'NON_BREAKING'
        forged = tx.put('contract_change_set', uuid4().hex, payload)
        with pytest.raises(EvidenceError, match='integrity_failure'):
            load_change_evidence(tx, forged['artifact_id'])


def test_concurrent_detection_is_one_immutable_record(database, repos, pair):
    def detect(_):
        with repos[0].transaction(database['tenants'][0]) as tx:
            return detect_and_persist(tx, pair[0]['artifact_id'], pair[1]['artifact_id'])['artifact_id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        identities = list(pool.map(detect, range(8)))
    assert len(set(identities)) == 1


def test_ordered_snapshot_pair_is_directional(database, repos, pair):
    with repos[0].transaction(database['tenants'][0]) as tx:
        forward = detect_and_persist(tx, pair[0]['artifact_id'], pair[1]['artifact_id'])
        reverse = detect_and_persist(tx, pair[1]['artifact_id'], pair[0]['artifact_id'])
        assert forward['artifact_id'] != reverse['artifact_id']
