from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

import air.repair_proposal as rp
from air.postgres import PostgresRepository, PostgresConfig, IdempotencyConflict
from air.dependency_impact import analyze_and_persist
from air.mapping_extraction import MAPPING_VERSION, register_adapter_mapping, extract_registered_dependencies
from test_workflow_evidence import saved
from test_repair_proposal import description, decide, authorize

pytestmark = pytest.mark.postgres


@pytest.fixture
def reviewer(database):
    login, password = 'reviewer_' + uuid4().hex, uuid4().hex
    with psycopg.connect(database['dsn'], autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(login),sql.Literal(password)))
        rp.bind_reviewer(admin, login, database['tenants'][0], 'human:' + login)
    dsn = psycopg.conninfo.make_conninfo(database['dsn'],user=login,password=password)
    return PostgresRepository(PostgresConfig(dsn,allow_insecure_local=True))


def create(tx,saved,*,downstream=False,**kwargs):
    p=json.loads(saved['impact']['payload'])
    row=p['analysis']['downstream_impacts' if downstream else 'impacts'][0]
    return rp.create_proposal(tx,saved['impact']['artifact_id'],row['impact_id'],description(),**kwargs)


@pytest.fixture
def proposal(database,repos,saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        return create(tx,saved)


@pytest.mark.parametrize('downstream',[False,True])
def test_proposal_persistence_and_exact_approval(database,repos,reviewer,saved,downstream):
    tenant=database['tenants'][0]
    with repos[0].transaction(tenant) as tx:
        p=create(tx,saved,downstream=downstream)
        assert create(tx,saved,downstream=downstream)==p
        with pytest.raises(rp.ProposalError): authorize(tx,p,saved['impact'])
    with reviewer.transaction(tenant) as tx:
        d=decide(tx,p)
        assert decide(tx,p)==d
    with repos[0].transaction(tenant) as tx:
        assert rp.load_proposal(tx,p['artifact_id'])==p
        assert authorize(tx,p,saved['impact'])==d
        for record in (p,d):
            assert len([a for a in tx.audit() if a['artifact_id']==record['artifact_id']])==1


def test_service_cannot_approve_or_self_provision(database,repos,proposal):
    for operation in ('approve','provision','spoof'):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with repos[0].transaction(database['tenants'][0]) as tx:
                if operation=='provision':
                    tx._connection.execute("INSERT INTO air_private.proposal_reviewers VALUES(session_user,'human:fake',true)")
                else:
                    if operation=='spoof': tx._connection.execute("SELECT set_config('air.reviewer','human:fake',true)")
                    decide(tx,proposal)


def test_rejection_retries_conflicts(database,reviewer,proposal,saved):
    with reviewer.transaction(database['tenants'][0]) as tx:
        d=decide(tx,proposal,'REJECTED');assert decide(tx,proposal,'REJECTED')==d
        with pytest.raises(rp.ProposalError): authorize(tx,proposal,saved['impact'])
        with pytest.raises(IdempotencyConflict): decide(tx,proposal)


def test_revision_supersedes_and_requires_new_approval(database,reviewer,proposal,saved):
    with reviewer.transaction(database['tenants'][0]) as tx:
        decide(tx,proposal)
        revised=create(tx,saved,supersedes=proposal['artifact_id'])
        assert json.loads(revised['payload'])['revision']==2
        with pytest.raises(rp.ProposalError): authorize(tx,proposal,saved['impact'])
        with pytest.raises(rp.ProposalError): decide(tx,proposal)
        with pytest.raises(rp.ProposalError): authorize(tx,revised,saved['impact'])
        decide(tx,revised); assert authorize(tx,revised,saved['impact'])


@pytest.mark.parametrize('identity',['unknown','foreign'])
def test_cross_tenant_operations_have_same_failure(database,repos,proposal,saved,identity):
    p=deepcopy(proposal)
    if identity=='unknown': p['artifact_id']=uuid4()
    with repos[1].transaction(database['tenants'][1]) as tx:
        for operation in (lambda:rp.load_proposal(tx,p['artifact_id']),lambda:decide(tx,p),lambda:authorize(tx,p,saved['impact'])):
            with pytest.raises(rp.ProposalError,match='not_found_or_not_authorized'): operation()
        assert tx._connection.execute('SELECT * FROM air.artifacts WHERE artifact_id=%s',(p['artifact_id'],)).fetchall()==[]
        with pytest.raises(ValueError): create(tx,saved)


@pytest.mark.parametrize('mutation',['impact','change','registry','target','tenant','revision','supersedes','hash','description'])
def test_db_rejects_invalid_proposals(database,repos,proposal,mutation):
    p=json.loads(proposal['payload'])
    if mutation=='impact': p['impact']['artifact_id']=str(uuid4())
    elif mutation=='change': p['change_evidence']['artifact_id']=str(uuid4())
    elif mutation=='registry': p['registry']['artifact_hash']='0'*64
    elif mutation=='target': p['impact_item']['dependency']['integration_id']='invented'
    elif mutation=='tenant': p['tenant_id']=str(database['tenants'][1])
    elif mutation=='revision': p['revision']=2
    elif mutation=='supersedes': p['supersedes']={'artifact_id':'malformed','artifact_hash':'0'*64}
    elif mutation=='description': p['description']['generator']='llm'
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx.put('repair_proposal','wrong' if mutation=='hash' else rp.digest(p),p)


@pytest.mark.parametrize('mutation',['hash','revision','proposal','reviewer','impact','decision','tenant','key'])
def test_db_rejects_forged_decisions(database,reviewer,proposal,mutation):
    with reviewer.transaction(database['tenants'][0]) as tx:
        d=decide(tx,proposal)
    p=json.loads(d['payload'])
    if mutation=='hash': p['proposal']['artifact_hash']='0'*64
    elif mutation=='revision': p['revision']=2
    elif mutation=='proposal': p['proposal']['artifact_id']=str(uuid4())
    elif mutation=='reviewer': p['reviewer']='human:forged'
    elif mutation=='impact': p['impact']['artifact_id']=str(uuid4())
    elif mutation=='decision': p['decision']='MAYBE'
    elif mutation=='tenant': p['tenant_id']=str(database['tenants'][1])
    with pytest.raises(psycopg.errors.CheckViolation):
        with reviewer.transaction(database['tenants'][0]) as tx:
            tx.put('repair_decision',str(uuid4()) if mutation=='key' else str(proposal['artifact_id']),p)


@pytest.mark.parametrize('kind',['proposal','decision'])
@pytest.mark.parametrize('verb',['UPDATE air.artifacts SET payload=payload','DELETE FROM air.artifacts'])
def test_immutable_proposal_and_audit(database,reviewer,proposal,kind,verb):
    with reviewer.transaction(database['tenants'][0]) as tx: d=decide(tx,proposal)
    record=proposal if kind=='proposal' else d
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with reviewer.transaction(database['tenants'][0]) as tx:
            tx._connection.execute(verb+' WHERE artifact_id=%s',(record['artifact_id'],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with reviewer.transaction(database['tenants'][0]) as tx:
            tx._connection.execute('DELETE FROM air.audit_events WHERE artifact_id=%s',(record['artifact_id'],))


@pytest.mark.parametrize('choices',[('APPROVED','APPROVED'),('APPROVED','REJECTED')])
def test_concurrent_decisions(database,reviewer,proposal,choices):
    def run(choice):
        try:
            with reviewer.transaction(database['tenants'][0]) as tx: return decide(tx,proposal,choice)
        except IdempotencyConflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,choices))
    if choices[0]==choices[1]: assert results[0]==results[1]
    else: assert results.count('conflict')==1


def test_automatic_mapping_impact_proposal(database,repos,saved):
    with repos[0].transaction(database['tenants'][0]) as tx:
        mapping=register_adapter_mapping(tx,{'mapping_version':MAPPING_VERSION,'tenant_id':str(tx.tenant_id),
            'snapshot_id':str(saved['snapshot']['artifact_id']),'adapter_id':'node0',
            'mappings':[{'mapping_id':'read','method':'GET','path':'/node0','bindings':[]}]})
        extracted=extract_registered_dependencies(tx,[mapping['artifact_id']],explicit_registry_id=saved['registry']['artifact_id'])
        impact=analyze_and_persist(tx,saved['changes']['artifact_id'],extracted['registry']['artifact_id'])
        p=create(tx,{**saved,'impact':impact},downstream=True)
        assert rp.load_proposal(tx,p['artifact_id'])==p


def test_raw_cross_tenant_links(database,repos,proposal):
    p=json.loads(proposal['payload']);p['tenant_id']=str(database['tenants'][1])
    with pytest.raises(psycopg.errors.CheckViolation):
        with repos[1].transaction(database['tenants'][1]) as tx:
            tx.put('repair_proposal',rp.digest(p),p)


@pytest.mark.parametrize('mutation',['hash','revision','current_impact'])
def test_stale_exact_authorization(database,reviewer,proposal,saved,mutation):
    with reviewer.transaction(database['tenants'][0]) as tx:
        decide(tx,proposal)
        args={'proposal_hash':'0'*64} if mutation=='hash' else {'revision':2} if mutation=='revision' else {'current_impact_id':uuid4()}
        with pytest.raises(rp.ProposalError): authorize(tx,proposal,saved['impact'],**args)


def test_db_stale_decision_cannot_bypass_api(database,reviewer,proposal,saved):
    with reviewer.transaction(database['tenants'][0]) as tx:
        d=decide(tx,proposal)
        create(tx,saved,supersedes=proposal['artifact_id'])
    with pytest.raises(psycopg.errors.CheckViolation):
        with reviewer.transaction(database['tenants'][0]) as tx:
            tx.put('repair_decision',str(proposal['artifact_id']),json.loads(d['payload']))


def test_concurrent_revision_and_approval_fail_closed(database,reviewer,proposal,saved):
    def run(action):
        try:
            with reviewer.transaction(database['tenants'][0]) as tx:
                return decide(tx,proposal) if action=='approve' else create(tx,saved,supersedes=proposal['artifact_id'])
        except rp.ProposalError: return None
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,['approve','revise']))
    assert results[1] is not None
    with reviewer.transaction(database['tenants'][0]) as tx:
        with pytest.raises(rp.ProposalError): authorize(tx,proposal,saved['impact'])


def test_concurrent_identical_proposals(database,repos,saved):
    def run(_):
        with repos[0].transaction(database['tenants'][0]) as tx: return create(tx,saved)
    with ThreadPoolExecutor(max_workers=2) as pool: first,second=pool.map(run,range(2))
    assert first==second


def test_missing_tenant_context_rejected(database,repos,proposal):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repos[0].transaction(database['tenants'][0]) as tx:
            tx._connection.execute("SELECT set_config('air.tenant_id','',true)")
            rp.load_proposal(tx,proposal['artifact_id'])


def test_reviewer_cannot_be_rebound(database,reviewer):
    login=psycopg.conninfo.conninfo_to_dict(reviewer.config.dsn)['user']
    with psycopg.connect(database['dsn'],autocommit=True) as admin:
        with pytest.raises(ValueError): rp.bind_reviewer(admin,login,database['tenants'][1],'human:other')
        with pytest.raises(ValueError): rp.bind_reviewer(admin,login,database['tenants'][0],'human:other')
