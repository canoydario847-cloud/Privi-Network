from starlette.testclient import TestClient
from privi_anchor.server import build_server, Settings
from privi_anchor.store import AnchorStore
from test_anchor import FakeChain


def test_readiness_distinguishes_liveness_missing_signer_and_gas(tmp_path):
    store = AnchorStore(str(tmp_path / 'ready.db'))
    def probe(chain):
        server = build_server(Settings(), chain, store)
        with TestClient(server.streamable_http_app(host='0.0.0.0', stateless_http=True, json_response=True)) as client:
            assert client.get('/health').status_code == 200
            return client.get('/ready')
    result = probe(None)
    assert result.status_code == 503
    assert result.json()['blockers'] == ['anchor_signer_not_configured']
    chain = FakeChain()
    assert probe(chain).status_code == 200
    chain.balance_wei = lambda: 0
    assert probe(chain).json()['blockers'] == ['anchor_gas_unavailable']
    def broken():
        raise RuntimeError('private credential should not leak')
    chain.latest_block = broken
    result = probe(chain)
    assert result.status_code == 503
    assert result.json()['blockers'] == ['anchor_chain_unreachable']
    assert 'private credential' not in result.text
