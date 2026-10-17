#!/usr/bin/env python3
"""Negative and synthetic-only operator + signed ceremony tests. No real credentials."""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE=Path(__file__).parent
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    out=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(out)
    return out

operator=module("operator_preflight",HERE/"operator-kit"/"operator_preflight.py")
ceremony=module("ceremony_verify",HERE/"ceremony_verify.py")
CHAIN="privi-mainnet-999"
EVM_ID=999991
IMAGE="registry.example.net/privi/evmd@sha256:"+"a"*64
CAP=10**27

def synthetic_chain():
    return {
        "chain_id":CHAIN,
        "app_state":{
            "bank":{"supply":[{"denom":"aprvi","amount":str(CAP)}]},
            "staking":{"params":{"bond_denom":"aprvi"}},
            "evm":{"params":{"evm_denom":"aprvi"}}
        }
    }

def make_operator_fixture(root):
    gen=json.dumps(synthetic_chain(),sort_keys=True,separators=(",",":")).encode()
    for label in ("validator","sentry"):
        state=root/(label+"-state")
        config=state/"config"
        config.mkdir(parents=True,exist_ok=True)
        state.chmod(0o700)
        (config/"genesis.json").write_bytes(gen)
        (config/"node_key.json").write_text('{"synthetic_node_label":"'+label+'"}')
        (config/"node_key.json").chmod(0o600)
        (config/"config.toml").write_text(
            '[p2p]\npex = '+('false' if label=="validator" else 'true')+'\n'
            'persistent_peers = "synthetic-peer@127.0.0.1:26656"\n'
            'private_peer_ids = "synthetic-private-sentry-id"\n'
            '[rpc]\nladdr = "tcp://127.0.0.1:26657"\n')
        (config/"app.toml").write_text(
            'minimum-gas-prices = "0.0001aprvi"\n[json-rpc]\nenable = false\n')
        if label=="validator":
            # Intentionally NOT A KEY, just permission-check fixture bytes.
            (config/"priv_validator_key.json").write_text('{"synthetic_only":true}')
            (config/"priv_validator_key.json").chmod(0o600)
    return hashlib.sha256(gen).hexdigest()

class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="privi-operator-synthetic-")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.digest=make_operator_fixture(self.root)

    def scan(self, chain=CHAIN, image=IMAGE, digest=None):
        return operator.verify(self.root,digest or self.digest,chain,EVM_ID,image)

    def test_safe_synthetic_config_passes_static_check(self):
        self.assertEqual([],self.scan())

    def test_wrong_genesis_fails(self):
        self.assertTrue(any("SHA-256" in x for x in self.scan(digest="b"*64)))

    def test_developer_chain_rejected(self):
        self.assertTrue(any("Cosmos chain ID" in x for x in self.scan(chain="local-4221")))

    def test_unpinned_node_image_rejected(self):
        self.assertTrue(any("image" in x for x in self.scan(image="latest")))

    def test_sentry_with_validator_key_rejected(self):
        (self.root/"sentry-state"/"config"/"priv_validator_key.json").write_text('{"synthetic_only":true}')
        self.assertTrue(any("sentry must not hold" in x for x in self.scan()))

    def test_reused_p2p_node_key_rejected(self):
        src=self.root/"validator-state"/"config"/"node_key.json"
        dst=self.root/"sentry-state"/"config"/"node_key.json"
        shutil.copy(src,dst)
        self.assertTrue(any("DIFFERENT P2P node keys" in x for x in self.scan()))

    def test_publicly_readable_validator_signer_rejected(self):
        key=self.root/"validator-state"/"config"/"priv_validator_key.json"
        key.chmod(0o644)
        self.assertTrue(any("signer permission" in x for x in self.scan()))

    def test_public_json_rpc_rejected(self):
        app=self.root/"validator-state"/"config"/"app.toml"
        app.write_text('minimum-gas-prices = "0.0001aprvi"\n[json-rpc]\nenable = true\n')
        self.assertTrue(any("JSON-RPC" in x for x in self.scan()))

class CeremonyTests(unittest.TestCase):
    def test_payload_rejects_demo_ids_and_digests(self):
        with self.assertRaises(ValueError):
            ceremony.canonical_payload("local-4221",262144,"a"*64,"b"*64)
        with self.assertRaises(ValueError):
            ceremony.canonical_payload(CHAIN,EVM_ID,"0"*64,"b"*64)

    def test_unsigned_registry_is_not_accepted(self):
        data=json.dumps({"chain_id":CHAIN}).encode()
        binary=b"synthetic dummy binary bytes, not executable"
        doc={
            "cosmos_chain_id":CHAIN,"evm_chain_id":EVM_ID,
            "genesis_sha256":hashlib.sha256(data).hexdigest(),
            "binary_sha256":hashlib.sha256(binary).hexdigest(),
            "operators":[]
        }
        problems=ceremony.validate(doc,data,binary)
        self.assertTrue(any("seven" in e for e in problems),problems)

    @unittest.skipUnless(shutil.which("openssl"),"OpenSSL is required for public Ed25519 test")
    def test_cryptographic_ed25519_signatures(self):
        genesis=json.dumps({"chain_id":CHAIN}).encode()
        binary=b"totally synthetic CI test, NOT mainnet software"
        gs=hashlib.sha256(genesis).hexdigest(); bs=hashlib.sha256(binary).hexdigest()
        payload=ceremony.canonical_payload(CHAIN,EVM_ID,gs,bs)
        with tempfile.TemporaryDirectory(prefix="privi-ci-crypto-fixture-") as d:
            base=Path(d)
            (base/"payload").write_bytes(payload)
            records=[]
            for i in range(7):
                priv=base/f"attestor{i}.pem"
                pub=base/f"attestor{i}.pub"
                sig=base/f"attestor{i}.sig"
                subprocess.run(["openssl","genpkey","-algorithm","ED25519","-out",str(priv)],
                    check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                subprocess.run(["openssl","pkey","-in",str(priv),"-pubout","-out",str(pub)],
                    check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                subprocess.run(["openssl","pkeyutl","-sign","-rawin","-inkey",str(priv),
                                "-in",str(base/"payload"),"-out",str(sig)],
                    check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                records.append({
                  "operator_id":f"synthetic-only-{i}",
                  "consensus_pubkey":"synthetic-not-real-consensus-pubkey-"+str(i)+"f"*55,
                  "attestation_public_key_pem":pub.read_text(),
                  "signature_base64":base64.b64encode(sig.read_bytes()).decode(),
                  "infrastructure_provider":f"synthetic-provider-{i%3}",
                  "region":f"synthetic-region-{i%3}",
                  "genesis_voting_power":100,
                  "independence_evidence_url":f"https://example.invalid/synthetic/{i}"
                })
            registry={
                "cosmos_chain_id":CHAIN,"evm_chain_id":EVM_ID,
                "genesis_sha256":gs,"binary_sha256":bs,
                "operators":records,"operator_independence_audit_complete":True,
                "externally_audited_release":True
            }
            self.assertEqual([],ceremony.validate(registry,genesis,binary))
            changed=copy.deepcopy(registry)
            changed["operators"][0]["signature_base64"]=base64.b64encode(b"\x00"*64).decode()
            self.assertTrue(any("signature FAILED" in x for x in ceremony.validate(changed,genesis,binary)))
            bad=copy.deepcopy(registry)
            bad["operators"][0]["genesis_voting_power"]=4000
            self.assertTrue(any("one third" in x for x in ceremony.validate(bad,genesis,binary)))

if __name__=="__main__": unittest.main()
