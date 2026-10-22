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
