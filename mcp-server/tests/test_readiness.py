import json
import urllib.request
from starlette.testclient import TestClient
from privi_verify.server import build_server
from privi_verify.config import Settings


def test_readiness_checks_anchor_dependency(tmp_path, monkeypatch):
    monkeypatch.delenv('PRIVI_ANCHOR_KEY', raising=False)
    server = build_server(Settings(db_path=str(tmp_path / 'ready.db')))
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, n): return json.dumps(self.data).encode()
    reply = Reply()
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: reply)
    with TestClient(server.streamable_http_app(host='0.0.0.0', stateless_http=True, json_response=True)) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/ready').json()['blockers'] == ['anchor_credentials_missing']
        monkeypatch.setenv('PRIVI_ANCHOR_KEY', 'test-only')
        reply.data = {'anchoring_enabled': False}
        assert client.get('/ready').json()['blockers'] == ['anchor_signer_not_configured']
        reply.data = {'anchoring_enabled': True, 'chain_reachable': True, 'gas_ok': True}
        assert client.get('/ready').status_code == 200
