from copy import deepcopy
from datetime import datetime, timezone
import json
from uuid import uuid4

import pytest

import air.repair_proposal as rp
from air.postgres import canonical_json, IdempotencyConflict


def description():
    return {'change_type': 'mapping_update', 'proposed_state': {'field': 'new_name'},
            'rationale': 'The referenced field changed', 'risk': 'medium',
            'generator': 'human', 'generator_version': 'manual-v1'}


class Memory:
    def __init__(self):
        self.tenant_id = uuid4()
        self.records = {}
        self._connection = self
    def put(self, kind, key, payload):
        encoded = canonical_json(payload)
        old = self.get(kind, key)
        if old:
            if old['payload'] != encoded:
                raise IdempotencyConflict('conflict')
            return old
        r = dict(tenant_id=self.tenant_id, artifact_id=uuid4(), kind=kind,
                 idempotency_key=key, payload=encoded, content_hash=rp.digest(payload),
                 created_at=datetime.now(timezone.utc))
        self.records[str(r['artifact_id'])] = r
        return r
    def get(self, kind, key):
        return next((r for r in self.records.values() if r['kind']==kind and r['idempotency_key']==key), None)
    def get_by_id(self, identity, *, kind):
        r = self.records.get(str(identity))
        return r if r and r['kind']==kind else None
    def execute(self, *args):
        return self
    def fetchone(self):
        return {'reviewer': 'human:alice'}


@pytest.fixture
def context(monkeypatch):
    tx = Memory()
    row = {'impact_id': 'a'*64, 'change_id': 'b'*64,
           'dependency': {'integration_id': 'orders', 'mapping_id': 'read'}}
    impact = tx.put('contract_dependency_impact', 'impact', {
        'analysis': {'impacts': [row]}, 'change_evidence': {'artifact_id': str(uuid4()), 'artifact_hash': 'c'*64},
        'registry': {'artifact_id': str(uuid4()), 'artifact_hash': 'd'*64}})
    def load(t, identity):
        return rp._get(t, identity, 'contract_dependency_impact')
    monkeypatch.setattr(rp, 'load_impact', load)
    monkeypatch.setattr(rp, '_lock', lambda *args: None)
    monkeypatch.setattr(rp, '_successor', lambda t, identity: next((r for r in t.records.values()
        if r['kind']=='repair_proposal' and (json.loads(r['payload']).get('supersedes') or {}).get('artifact_id')==str(identity)), None))
    return tx, impact, row['impact_id']


def make(context, desc=None, **kwargs):
    tx, impact, item = context
    return rp.create_proposal(tx, impact['artifact_id'], item, desc or description(), **kwargs)


def decide(tx, p, choice='APPROVED', **kwargs):
    params = dict(proposal_hash=p['content_hash'], revision=json.loads(p['payload'])['revision'], decision=choice, confirmed=True)
    params.update(kwargs)
    return rp.decide(tx, p['artifact_id'], **params)


def authorize(tx, p, impact, **kwargs):
    params = dict(proposal_hash=p['content_hash'], revision=json.loads(p['payload'])['revision'], current_impact_id=impact['artifact_id'])
    params.update(kwargs)
    return rp.authorization(tx, p['artifact_id'], **params)


def test_creation_canonical_idempotent_reload(context):
    tx, impact, _ = context
    p = make(context)
    assert p == make(context, dict(reversed(list(description().items()))))
    assert rp.load_proposal(tx,p['artifact_id']) == p
    body = json.loads(p['payload'])
    assert p['content_hash'] == p['idempotency_key'] == rp.digest(body)
    assert body['impact'] == rp.reference(impact)
    assert body['revision'] == 1
    assert tx.get('repair_decision', str(p['artifact_id'])) is None
    with pytest.raises(rp.ProposalError, match='not_authorized'): authorize(tx,p,impact)


@pytest.mark.parametrize('choice', ['APPROVED','REJECTED'])
def test_decisions_are_explicit_immutable_and_idempotent(context, choice):
    tx, impact, _ = context; p = make(context)
    d = decide(tx,p,choice)
    assert decide(tx,p,choice) == d
    assert json.loads(d['payload'])['proposal'] == rp.reference(p)
    if choice=='APPROVED': assert authorize(tx,p,impact)==d
    else:
        with pytest.raises(rp.ProposalError): authorize(tx,p,impact)
    with pytest.raises(IdempotencyConflict): decide(tx,p,'REJECTED' if choice=='APPROVED' else 'APPROVED')


def test_revision_invalidates_old_authorization(context):
    tx, impact, _ = context; p = make(context); decide(tx,p)
    desc=description(); desc['proposed_state']={'field':'better'}
    revised=make(context,desc,supersedes=p['artifact_id'])
    assert revised==make(context,desc,supersedes=p['artifact_id'])
    assert revised['content_hash'] != p['content_hash']
    assert json.loads(revised['payload'])['revision']==2
    for action in (lambda: authorize(tx,p,impact), lambda: decide(tx,p), lambda: authorize(tx,revised,impact)):
        with pytest.raises(rp.ProposalError): action()
    decide(tx,revised); assert authorize(tx,revised,impact)
    with pytest.raises(rp.ProposalError,match='already_superseded'):
        make(context,supersedes=p['artifact_id'])


@pytest.mark.parametrize('changes', [{'confirmed':False},{'confirmed':1},{'decision':'PENDING'}, {'proposal_hash':'0'*64},{'revision':2},{'revision':True}])
def test_invalid_decision(context, changes):
    tx, _, _=context; p=make(context)
    with pytest.raises(rp.ProposalError): decide(tx,p,**changes)


@pytest.mark.parametrize('changes', [{'proposal_hash':'0'*64},{'revision':2},{'revision':True},{'current_impact_id':uuid4()}])
def test_authorization_binding(context,changes):
    tx,impact,_=context;p=make(context);decide(tx,p)
    with pytest.raises(rp.ProposalError): authorize(tx,p,impact,**changes)


@pytest.mark.parametrize('field,value', [('risk','none'),('generator','llm'),('change_type','execute'),('rationale',''),('proposed_state',{}),('proposed_state','code'),('generator_version',''),('rationale','x\x00')])
def test_invalid_description(field,value):
    d=description(); d[field]=value
    with pytest.raises(rp.ProposalError): rp.normalize_description(d)


def test_missing_foreign_malformed_evidence(context):
    tx, impact,item=context
    for identity in (uuid4(), 'bad', None):
        with pytest.raises(rp.ProposalError): rp.create_proposal(tx,identity,item,description())
        with pytest.raises(rp.ProposalError): rp.load_proposal(tx,identity)
    with pytest.raises(rp.ProposalError): rp.create_proposal(tx,impact['artifact_id'],'unknown',description())
    p=make(context); p['tenant_id']=uuid4()
    with pytest.raises(rp.ProposalError,match='not_found_or_not_authorized'): rp.load_proposal(tx,p['artifact_id'])


def test_tampered_payload_fails(context):
    tx,_,_=context;p=make(context)
    p['payload']=p['payload'].replace('medium','high')
    with pytest.raises(rp.ProposalError,match='integrity_failure'): rp.load_proposal(tx,p['artifact_id'])


@pytest.mark.parametrize('mutation',['missing','null','wrong_type','version','revision','target'])
def test_malformed_persisted_proposal_fails_closed(context,mutation):
    tx,_,_=context;p=make(context);body=json.loads(p['payload'])
    if mutation=='missing': del body['impact']
    elif mutation=='null': body['impact']=None
    elif mutation=='wrong_type': body['impact']=[]
    elif mutation=='version': body['proposal_version']='future'
    elif mutation=='revision': body['revision']=3
    else: body['impact_item']['dependency']['integration_id']='fake'
    p['payload']=canonical_json(body);p['content_hash']=rp.digest(body);p['idempotency_key']=p['content_hash']
    with pytest.raises(rp.ProposalError): rp.load_proposal(tx,p['artifact_id'])


def test_revision_chain_bound(context):
    tx,_,_=context;p=make(context)
    for _ in range(99): p=make(context,supersedes=p['artifact_id'])
    assert json.loads(p['payload'])['revision']==100
    with pytest.raises(rp.ProposalError,match='revision_limit'): make(context,supersedes=p['artifact_id'])


@pytest.mark.parametrize('decision',['APPROVED','REJECTED'])
def test_lifecycle_is_derived_from_immutable_history(context,decision):
    tx,_,_=context;p=make(context)
    assert rp.proposal_status(tx,p['artifact_id'])=='PROPOSED'
    decide(tx,p,decision)
    assert rp.proposal_status(tx,p['artifact_id'])==decision
    revised=make(context,supersedes=p['artifact_id'])
    assert rp.proposal_status(tx,p['artifact_id'])=='SUPERSEDED'
    assert rp.proposal_status(tx,revised['artifact_id'])=='PROPOSED'


@pytest.mark.parametrize('mutation',['extra','oversized','nan'])
def test_description_strict_bounds(mutation):
    d=description()
    if mutation=='extra': d['execute']=True
    elif mutation=='oversized': d['proposed_state']={'field':'x'*65536}
    else: d['proposed_state']={'field':float('nan')}
    with pytest.raises(ValueError): rp.normalize_description(d)
