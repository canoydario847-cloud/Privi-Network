import json
import os
import tempfile
from pathlib import Path

os.environ["LIFE_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.sqlite3")
os.environ["LIFE_COOKIE_SECURE"] = "0"
os.environ["LIFE_DEV_TRIAL_CREDITS"] = "10"
os.environ["OPENAI_API_KEY"] = "mock-not-a-real-key"
os.environ["OPENAI_MODEL"] = "mock"
os.environ["ANTHROPIC_API_KEY"] = "mock-not-a-real-key"
os.environ["ANTHROPIC_MODEL"] = "mock"
os.environ["PRVI_MAINNET_PAYMENTS_ENABLED"] = "0"
os.environ["PRIVI_COGVATIVE_ED25519_SEED"] = "01" * 32

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
import app
import agents

client = TestClient(app.app)

def member():
    email = os.urandom(6).hex() + "@example.com"
    created = client.post("/api/auth/signup", json={"email": email, "password": "strong_password_123"})
    assert created.status_code == 200, created.text
    account = Account.create()
    c = client.post("/api/wallet/challenge", json={"wallet": account.address})
    assert c.status_code == 200
    message = c.json()["message"]
    sig = Account.sign_message(encode_defunct(text=message), account.key).signature.hex()
    linked = client.post("/api/wallet/link", json={"wallet": account.address, "signature": "0x"+sig})
    assert linked.status_code == 200, linked.text
    return linked.json()

def test_membership_wallet_and_separate_projects():
    u=member()
    assert u["wallet"].startswith("0x")
    a=client.post("/api/projects", json={"title": "Website", "kind": "code"})
    b=client.post("/api/projects", json={"title": "Book", "kind": "writing"})
    assert a.status_code == b.status_code == 200
    assert a.json()["id"] != b.json()["id"]
    p=a.json()["id"]
    good=client.put(f"/api/projects/{p}/files",json={"path":"src/index.js","content":"hello","expected_version":0})
    assert good.status_code == 200
    conflict=client.put(f"/api/projects/{p}/files",json={"path":"src/index.js","content":"bad","expected_version":0})
    assert conflict.status_code == 409
    wrong=client.put(f"/api/projects/{p}/files",json={"path":"../secrets","content":"bad","expected_version":0})
    assert wrong.status_code == 400

def test_agents_work_in_parallel_then_merge_with_version_protection(monkeypatch):
    user=member()
    p=client.post("/api/projects",json={"title":"Joint Software","kind":"code"}).json()["id"]
    async def simulated(provider,instructions,prompt):
        return json.dumps({"summary":provider+" added an isolated file",
                           "files":[{"path":"src/"+provider+".py","content":"AGENT = '"+provider+"'\n"}]})
    monkeypatch.setattr(agents,"generate",simulated)
    done=client.post(f"/api/projects/{p}/run-team",json={"agents":["chatgpt","claude"],"task":"Build independent code modules"})
    assert done.status_code == 200, done.text
    assert user["credits"]-4 == done.json()["credits"]
    proposals=client.get(f"/api/projects/{p}/proposals").json()
    assert len(proposals)==2
    for proposal in proposals:
        merged=client.post(f"/api/projects/{p}/proposals/{proposal['id']}/apply")
        assert merged.status_code==200, merged.text
    shared=client.get(f"/api/projects/{p}/files").json()
    assert set(f["path"] for f in shared)=={"src/chatgpt.py","src/claude.py"}
    assert all(f["version"]==1 for f in shared)
    assert client.post(f"/api/projects/{p}/proposals/{proposals[0]['id']}/apply").status_code==200

def test_payments_disabled_and_no_cross_user_file_access():
    one=member()
    p=client.post("/api/projects",json={"title":"Private Code","kind":"code"}).json()["id"]
    denied=client.post("/api/wallet/quote",json={"credits":10})
    assert denied.status_code==503
    two=member()
    forbidden=client.get(f"/api/projects/{p}/files")
    assert forbidden.status_code==404
    assert client.post("/api/internal/charge",json={"user_id":one["id"],
        "service":"life_backup","idempotency_key":"unique_charge_1"}).status_code==403

def test_untrusted_code_proposal_is_never_executed():
    assert agents.extract_code_proposal("some text") is None
    try:
        agents.extract_code_proposal(json.dumps({"files":[{"path":"../../.env","content":"attack"}]}))
        assert False, "Expected traversal refusal"
    except ValueError:
        pass

def test_reject_cross_origin_writes():
    response=client.post("/api/auth/signup",headers={"origin":"https://evil.example"},
       json={"email":"attack@example.com","password":"strong_password_123"})
    assert response.status_code==403


def test_service_charge_is_idempotent_and_fee_is_fractional(monkeypatch):
    user=member()
    key='s'*48
    monkeypatch.setenv('PRIVI_SERVICE_KEYS_JSON',json.dumps({'life_backup':key}))
    payload={'user_id':user['id'],'service':'life_backup','idempotency_key':'backup-idempotent-24680'}
    first=client.post('/api/internal/charge',headers={'x-privi-service-key':key},json=payload)
    second=client.post('/api/internal/charge',headers={'x-privi-service-key':key},json=payload)
    assert first.status_code==second.status_code==200
    assert first.json()['balance']==second.json()['balance']==9
    ledger=client.get('/api/wallet/ledger').json()
    record=next(e for e in ledger if e['idempotency']=='backup-idempotent-24680')
    assert record['platform_fee_micros']==100000


def test_failed_provider_is_refunded(monkeypatch):
    user=member()
    project=client.post('/api/projects',json={'title':'Refund Test','kind':'code'}).json()['id']
    async def unavailable(*args,**kwargs):
        raise RuntimeError('offline')
    monkeypatch.setattr(agents,'generate',unavailable)
    outcome=client.post('/api/projects/'+project+'/run-team',json={'agents':['chatgpt'],'task':'Write code safely'})
    assert outcome.status_code==200
    assert outcome.json()['credits']==user['credits']
    assert outcome.json()['runs'][0]['status']=='failed'


def test_team_up_assigns_distinct_roles_and_proposes_files_concurrently(monkeypatch):
    import asyncio
    member()
    project=client.post('/api/projects',json={'title':'Team Up Code','kind':'code'}).json()['id']
    saw=set()
    both=asyncio.Event()
    async def mock(provider, instructions, prompt):
        saw.add(provider)
        if len(saw)==2:
            both.set()
        await asyncio.wait_for(both.wait(),timeout=1)
        assert 'Your assigned Team Up role:' in prompt
        return json.dumps({'summary':provider,'files':[
            {'path':'src/'+provider+'.py','content':'# teamwork'}]})
    monkeypatch.setattr(agents,'generate',mock)
    result=client.post('/api/projects/'+project+'/run-team',json={
        'agents':['chatgpt','claude'],'task':'Build a full application','mode':'team_up'})
    assert result.status_code==200,result.text
    assert result.json()['mode']=='team_up'
    assert len(set(result.json()['assignments'].values()))==2
    assert set(saw)=={'chatgpt','claude'}
    assert len(client.get('/api/projects/'+project+'/proposals').json())==2
    assert len(client.get('/api/projects/'+project+'/files').json())==0  # human merge required


def test_team_up_rejects_one_agent_or_noncode_project():
    member()
    project=client.post('/api/projects',json={'title':'Novel Draft','kind':'writing'}).json()['id']
    result=client.post('/api/projects/'+project+'/run-team',json={
        'agents':['chatgpt','claude'],'task':'Write stories together','mode':'team_up'})
    assert result.status_code==400
    code=client.post('/api/projects',json={'title':'Coding Together','kind':'code'}).json()['id']
    assert client.post('/api/projects/'+code+'/run-team',json={
        'agents':['chatgpt'],'task':'Build code','mode':'team_up'}).status_code==400


def test_fast_lane_uses_fastest_success_and_member_scoped_cache(monkeypatch):
    import asyncio
    u=member()
    p=client.post('/api/projects',json={'title':'Fast lane','kind':'research'}).json()['id']
    called=[]
    async def mock(name,instructions,prompt):
        called.append(name)
        await asyncio.sleep(.02 if name=='claude' else .3)
        return name+' answered'
    monkeypatch.setattr(agents,'generate',mock)
    before=u['credits']
    req={'question':'What is the architecture of this system?',
         'providers':['chatgpt','claude']}
    answer=client.post('/api/projects/'+p+'/fast-answer',json=req)
    assert answer.status_code==200,answer.text
    assert answer.json()['provider']=='claude'
    assert answer.json()['quantum_hardware_used'] is False
    assert answer.json()['charged_credits']==4
    assert before-4==client.get('/api/me').json()['credits']
    assert len(called)==2
    second=client.post('/api/projects/'+p+'/fast-answer',json=req)
    assert second.status_code==200
    assert second.json()['cached'] is True
    assert second.json()['charged_credits']==0
    assert len(called)==2
    other=member()
    assert client.post('/api/projects/'+p+'/fast-answer',json=req).status_code==404


def test_fast_lane_fallback_and_refunds_failed_request(monkeypatch):
    import asyncio
    u=member()
    p=client.post('/api/projects',json={'title':'Fault tolerance','kind':'code'}).json()['id']
    async def mock(name,instructions,prompt):
        if name=='chatgpt':
            raise RuntimeError('simulated unavailable provider')
        await asyncio.sleep(.005)
        return 'usable answer'
    monkeypatch.setattr(agents,'generate',mock)
    response=client.post('/api/projects/'+p+'/fast-answer',json={
        'question':'Answer despite failure','providers':['chatgpt','claude']})
    assert response.status_code==200,response.text
    assert response.json()['provider']=='claude'
    # First provider failed and was refunded. Second provider cost 2.
    assert client.get('/api/me').json()['credits']==u['credits']-2


def test_asset_registry_never_fakes_ai_coins_or_live_swaps(monkeypatch):
    import multichain
    member()
    reg=client.get('/api/networks/assets')
    assert reg.status_code==200
    assert reg.json()['swap_live'] is False
    assert all(not item['official_crypto_token_verified']
        for item in reg.json()['agent_providers'])
    assert client.post('/api/networks/swap/quote',json={
        'from_asset':'GROK','to_asset':'PRVI','amount':'1'}).status_code==503
    monkeypatch.setenv('PRIVI_REVIEWED_ASSETS_JSON',json.dumps([{
        'symbol':'SAMP','chain_id':8453,'contract':'0x'+'1'*40,'decimals':18}]))
    assets=multichain.validated_assets()
    assert len(assets)==1
    assert assets[0]['swap_enabled'] is False
    assert assets[0]['provider_affiliation']=='not_asserted'
    monkeypatch.setenv('PRIVI_REVIEWED_ASSETS_JSON',json.dumps([{
        'symbol':'FAKE','chain_id':8453,'contract':'0x'+'0'*40,'decimals':18}]))
    assert multichain.validated_assets()==[]


def test_staging_demo_disables_real_wallet_and_payments(monkeypatch):
    import app as application
    monkeypatch.setattr(application,'STAGING_MODE',True)
    monkeypatch.setenv('LIFE_STAGING_ONLY','1')
    try:
        client.post('/api/auth/logout')
        demo=client.post('/api/auth/demo')
        assert demo.status_code==200,demo.text
        assert demo.json()['credits']==60
        assert demo.json()['email'].endswith('@example.invalid')
        assert client.post('/api/wallet/challenge',json={'wallet':demo.json()['wallet']}).status_code==403
        assert client.post('/api/wallet/quote',json={'credits':2}).status_code==503
        assert client.post('/api/auth/signup',json={'email':'real@example.com','password':'123456789012'}).status_code==403
        catalog=client.get('/api/catalog').json()
        assert len([x for x in catalog['agents'] if x.get('simulation')])==3
        prj=client.post('/api/projects',json={'title':'Sandbox App','kind':'code'}).json()['id']
        outcome=client.post('/api/projects/'+prj+'/run-team',json={
            'agents':['demo-frontend','demo-backend'],'task':'Propose sample code',
            'mode':'team_up'})
        assert outcome.status_code==200,outcome.text
        assert len(client.get('/api/projects/'+prj+'/proposals').json())==2
        assert len(client.get('/api/projects/'+prj+'/files').json())==0
    finally:
        client.post('/api/auth/logout')
        monkeypatch.setattr(application,'STAGING_MODE',False)


def test_cogvative_signs_every_saved_line_and_preserves_inherited_authorship():
    import cogvative
    person=member()
    p=client.post('/api/projects',json={'title':'Cogvative signed code','kind':'code'}).json()['id']
    one=client.put('/api/projects/'+p+'/files',json={
        'path':'src/hello.py','content':'alpha = 1\nbeta = 2\n','expected_version':0})
    assert one.status_code==200,one.text
    assert one.json()['cogvative']['signature_status']=='ed25519_signed'
    eid=one.json()['cogvative']['event_id']
    detail=client.get('/api/projects/'+p+'/cogvative/event/'+eid)
    assert detail.status_code==200
    assert detail.json()['verification']=='ed25519_verified'
    assert len(detail.json()['lines'])==2
    assert all(line['author_agent']=='life-member:'+person['id'] for line in detail.json()['lines'])
    assert all(line['author_time'].endswith('Z') for line in detail.json()['lines'])
    assert detail.json()['event']['prvi_deploy_wei'] is None
    two=client.put('/api/projects/'+p+'/files',json={
        'path':'src/hello.py','content':'alpha = 1\nbeta = 3\n','expected_version':1})
    assert two.status_code==200,two.text
    d=client.get('/api/projects/'+p+'/cogvative/event/'+two.json()['cogvative']['event_id']).json()
    assert d['verification']=='ed25519_verified'
    assert d['lines'][0]['origin_event']==eid
    assert d['lines'][1]['origin_event']!=eid
    assert d['lines'][0]['author_time']==detail.json()['lines'][0]['author_time']
    assert d['event']['prev_event_sha256']==detail.json()['event']['event_hash']


def test_cogvative_agent_proposal_and_royalty_call(monkeypatch):
    import json
    user=member()
    p=client.post('/api/projects',json={'title':'Agent Royalty Code','kind':'code'}).json()['id']
    async def mocked(provider,instructions,prompt):
        return json.dumps({'summary':'agent wrote code','files':[{
            'path':'src/agent.py','content':'x = 10\ny = x\n'}]})
    monkeypatch.setattr(agents,'generate',mocked)
    run=client.post('/api/projects/'+p+'/run-team',json={
        'agents':['chatgpt'],'task':'Write one source file'})
    assert run.status_code==200,run.text
    signed=client.get('/api/projects/'+p+'/cogvative/proposals')
    assert signed.status_code==200
    assert len(signed.json())==1
    assert signed.json()[0]['signature_hex']
    proposal=client.get('/api/projects/'+p+'/proposals').json()[0]
    applied=client.post('/api/projects/'+p+'/proposals/'+proposal['id']+'/apply')
    assert applied.status_code==200,applied.text
    events=client.get('/api/projects/'+p+'/cogvative').json()
    assert len(events)==1
    assert events[0]['agent']=='chatgpt'
    assert events[0]['credit_cost']==2
    eid=events[0]['id']
    before=client.get('/api/me').json()['credits']
    first=client.post('/api/projects/'+p+'/cogvative/code-use',json={
        'event_id':eid,'idempotency_key':'code-call-unique-123456'})
    assert first.status_code==200,first.text
    assert first.json()['charged_credits']==1
    assert first.json()['royalty_micros']==400000
    second=client.post('/api/projects/'+p+'/cogvative/code-use',json={
        'event_id':eid,'idempotency_key':'code-call-unique-123456'})
    assert second.status_code==200
    assert second.json()['repeat'] is True
    assert client.get('/api/me').json()['credits']==before-1
    r=client.get('/api/projects/'+p+'/cogvative/royalty-balances')
    assert r.status_code==200,r.text
    assert len(r.json()['amounts'])==1
    assert r.json()['amounts'][0]['agent']=='chatgpt'
    assert r.json()['amounts'][0]['amount_micros']==400000
    assert r.json()['amounts'][0]['status']=='awaiting_wallet_claim'
    assert client.post('/api/projects/'+p+'/cogvative/code-use',json={
        'event_id':'bogus','idempotency_key':'code-call-unique-123456'}).status_code==409
    assert client.post('/api/projects/'+p+'/cogvative/'+eid+'/deployment',json={
        'tx_hash':'0x'+'a'*64}).status_code==503


def test_cogvative_requires_issuer_key_except_explicit_sandbox(monkeypatch):
    import cogvative
    person=member()
    p=client.post('/api/projects',json={'title':'Signing fail closed','kind':'code'}).json()['id']
    monkeypatch.delenv('PRIVI_COGVATIVE_ED25519_SEED',raising=False)
    import pytest
    with pytest.raises(RuntimeError,match="signing key required"):
        client.put('/api/projects/'+p+'/files',json={
            'path':'src/cannot.py','content':'a=1\n','expected_version':0})
    assert client.get('/api/projects/'+p+'/files').json()==[]


def _bnb_test_setup(monkeypatch):
    import hashlib
    import app as application
    contract='0xbf154ff2577f4b85db7b2ee910db5880d06e0f64'
    treasury='0x'+'9'*40
    code='0x6001600055'
    monkeypatch.setenv('BNB_PRIV_PAYMENTS_ENABLED','1')
    monkeypatch.setenv('BNB_PRIV_RPC_URL','https://example.org/verified-bsc-rpc')
    monkeypatch.setenv('BNB_PRIV_TOKEN_ADDRESS',contract)
    monkeypatch.setenv('BNB_PRIV_TREASURY_ADDRESS',treasury)
    monkeypatch.setenv('BNB_PRIV_CODE_SHA256',hashlib.sha256(bytes.fromhex(code[2:])).hexdigest())
    monkeypatch.setenv('BNB_PRIV_DECIMALS','18')
    monkeypatch.setenv('BNB_PRIV_UNITS_PER_CREDIT',str(10**18))
    monkeypatch.setenv('BNB_PRIV_REQUIRED_CONFIRMATIONS','12')
    monkeypatch.setattr(application,'COOKIE_SECURE',True)
    monkeypatch.setattr(application,'STAGING_MODE',False)
    return contract,treasury,code


def test_bnb_priv_real_token_payment_mocks_confirmed_log_and_blocks_replay(monkeypatch):
    import app as application
    import bnb_priv
    import store as datastore
    account=member()
    contract,treasury,code=_bnb_test_setup(monkeypatch)
    tx_hash='0x'+'a'*64
    block_hash='0x'+'b'*64
    quote_data={}
    async def fake_rpc(url,method,params):
        if method=='eth_chainId': return '0x38'
        if method=='eth_getCode': return code
        if method=='eth_call': return hex(18)
        if method=='eth_blockNumber': return hex(140)
        if method=='eth_getBlockByNumber':
            return {'hash':block_hash,'timestamp':hex(datastore.now()+5)}
        if method=='eth_getTransactionByHash':
            return {'from':account['wallet'],'to':contract,'input':quote_data['token_transfer_data'],
                    'value':'0x0','blockHash':block_hash,'blockNumber':hex(121)}
        if method=='eth_getTransactionReceipt':
            return {'transactionHash':tx_hash,'status':'0x1','blockHash':block_hash,'blockNumber':hex(121),
                    'logs':[{'address':contract,'topics':[
                        bnb_priv.TRANSFER_TOPIC,
                        '0x'+'0'*24+account['wallet'][2:].lower(),
                        '0x'+'0'*24+treasury[2:].lower()],
                        'data':hex(int(quote_data['amount_units']))}]}
        raise AssertionError(method)
    monkeypatch.setattr(application,'rpc',fake_rpc)
    status=client.get('/api/payments/bnb-priv/status')
    assert status.status_code==200
    assert status.json()['payments_configured']
    assert status.json()['chain_id']==56
    assert status.json()['symbol_not_independently_verified']
    quote=client.post('/api/payments/bnb-priv/quote',json={'credits':3})
    assert quote.status_code==200,quote.text
    quote_data.update(quote.json())
    assert quote_data['amount_units']==str(3*10**18)
    assert quote_data['amount_fiat_usd'] is None
    before=client.get('/api/me').json()['credits']
    paid=client.post('/api/payments/bnb-priv/redeem',json={
       'quote_id':quote_data['quote_id'],'tx_hash':tx_hash})
    assert paid.status_code==200,paid.text
    assert paid.json()['credits_added']==3
    assert paid.json()['fiat_income_usd'] is None
    assert client.get('/api/me').json()['credits']==before+3
    reused=client.post('/api/payments/bnb-priv/redeem',json={
       'quote_id':quote_data['quote_id'],'tx_hash':tx_hash})
    assert reused.status_code==409
    assert client.get('/api/me').json()['credits']==before+3


def test_bnb_priv_payment_fails_closed_for_wrong_chain_and_missing_treasury(monkeypatch):
    import app as application
    account=member()
    contract,treasury,code=_bnb_test_setup(monkeypatch)
    async def bogus_chain(url,method,params):
        return '0x61' if method=='eth_chainId' else code
    monkeypatch.setattr(application,'rpc',bogus_chain)
    assert client.post('/api/payments/bnb-priv/quote',json={'credits':1}).status_code==503
    monkeypatch.setenv('BNB_PRIV_TREASURY_ADDRESS','')
    assert client.get('/api/payments/bnb-priv/status').json()['payments_configured'] is False
    assert client.post('/api/payments/bnb-priv/quote',json={'credits':1}).status_code==503
    monkeypatch.setenv('BNB_PRIV_TREASURY_ADDRESS',treasury)
    monkeypatch.setattr(application,'STAGING_MODE',True)
    assert client.post('/api/payments/bnb-priv/quote',json={'credits':1}).status_code==503


def test_bnb_priv_receipt_rejects_forged_or_underpaid_logs(monkeypatch):
    import app as application
    import bnb_priv
    import store as datastore
    account=member()
    contract,treasury,code=_bnb_test_setup(monkeypatch)
    # All RPC responses below are deterministic test fixtures.
    async def valid_rpc(url,method,params):
        if method=='eth_chainId': return '0x38'
        if method=='eth_getCode': return code
        if method=='eth_call': return '0x12'
        if method=='eth_blockNumber': return '0x90'
        if method=='eth_getBlockByNumber':
            return {'hash':'0x'+'b'*64,'timestamp':hex(datastore.now())}
        if method=='eth_getTransactionByHash':
            return {'from':account['wallet'],'to':contract,
                    'input':bnb_priv.calldata(treasury,10**18),'value':'0x0',
                    'blockHash':'0x'+'b'*64,'blockNumber':'0x80'}
        if method=='eth_getTransactionReceipt':
            return {'transactionHash':'0x'+'c'*64,'status':'0x1','blockHash':'0x'+'b'*64,
                    'blockNumber':'0x80','logs':[{'address':contract,'topics':[
                        bnb_priv.TRANSFER_TOPIC,'0x'+'0'*24+account['wallet'][2:].lower(),
                        '0x'+'0'*24+treasury[2:].lower()], 'data':hex(10**18-1)}]}
        raise AssertionError(method)
    monkeypatch.setattr(application,'rpc',valid_rpc)
    quote=client.post('/api/payments/bnb-priv/quote',json={'credits':1})
    assert quote.status_code==200,quote.text
    previous=client.get('/api/me').json()['credits']
    denied=client.post('/api/payments/bnb-priv/redeem',json={
        'quote_id':quote.json()['quote_id'],'tx_hash':'0x'+'c'*64})
    assert denied.status_code==409,denied.text
    assert client.get('/api/me').json()['credits']==previous
    monkeypatch.setenv('BNB_PRIV_UNITS_PER_CREDIT',str(2*10**18))
    assert client.post('/api/payments/bnb-priv/redeem',json={
        'quote_id':quote.json()['quote_id'],'tx_hash':'0x'+'c'*64}).status_code==409
