#!/usr/bin/env python3
"""Public-key-only, read-only Genesis ceremony verification.

Operators sign a canonical ASCII payload with their own separate Ed25519
*attestation* keys; these keys are NOT the CometBFT private validator keys.
Valid signatures cannot themselves prove actual operator independence or audits.
"""
import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

HEX=re.compile(r"^[a-f0-9]{64}$")
CHAIN=re.compile(r"^privi-[a-z0-9-]{5,55}$")
DEMO_IDS={262144,4221,56,97,1}

def canonical_payload(chain, evm_id, genesis_sha, binary_sha):
    if not CHAIN.fullmatch(chain) or chain in ("local-4221","privi-dev-1"):
        raise ValueError("Approved non-demo Cosmos chain ID required")
    if type(evm_id) is not int or evm_id<1000 or evm_id in DEMO_IDS:
        raise ValueError("Approved non-demo numeric EVM chain ID required")
    for h in (genesis_sha,binary_sha):
        if not isinstance(h,str) or not HEX.fullmatch(h) or h=="0"*64:
            raise ValueError("Real SHA-256 digests required")
    return ("Privi Mainnet Genesis Ceremony v1\n"
            +f"cosmos_chain_id={chain}\n"
            +f"evm_chain_id={evm_id}\n"
            +f"genesis_sha256={genesis_sha}\n"
            +f"binary_sha256={binary_sha}\n").encode("ascii")

def verify_ed25519(payload, public_pem, base64sig):
    try:
        sig=base64.b64decode(base64sig,validate=True)
        if len(sig)!=64 or not isinstance(public_pem,str) or len(public_pem)>4096 or not public_pem.startswith("-----BEGIN PUBLIC KEY-----"):
            return False
        with tempfile.TemporaryDirectory(prefix="privi-attestation-check-") as d:
            root=Path(d)
            (root/"payload").write_bytes(payload)
            (root/"operator.pub").write_text(public_pem,encoding="ascii")
            (root/"signature").write_bytes(sig)
            result=subprocess.run(["openssl","pkeyutl","-verify","-rawin","-pubin",
                                  "-inkey",str(root/"operator.pub"),
                                  "-sigfile",str(root/"signature"),
                                  "-in",str(root/"payload")],
                                  capture_output=True,timeout=15,check=False)
            return result.returncode==0
    except (ValueError, OSError, subprocess.TimeoutExpired, UnicodeError):
        return False

def validate(registry, genesis_bytes, binary_bytes):
    errors=[]
    def need(ok,reason):
        if not ok: errors.append(reason)
    chain=registry.get("cosmos_chain_id")
    eid=registry.get("evm_chain_id")
    gs=hashlib.sha256(genesis_bytes).hexdigest()
    bs=hashlib.sha256(binary_bytes).hexdigest()
    try:
        payload=canonical_payload(chain,eid,gs,bs)
    except (ValueError,TypeError) as e:
        return [str(e)]
    need(registry.get("genesis_sha256")==gs,
         "Registry genesis digest does not match byte-for-byte genesis")
    need(registry.get("binary_sha256")==bs,
         "Registry binary digest does not match exact approved binary")
    try:
        genesis=json.loads(genesis_bytes)
        need(genesis.get("chain_id")==chain, "Genesis chain ID does not match ceremony")
    except (ValueError,AttributeError,UnicodeError):
        errors.append("Invalid Cosmos genesis JSON")
    rows=registry.get("operators")
    if not isinstance(rows,list) or len(rows)<7:
        errors.append("At least seven operator attestations required")
        rows=rows if isinstance(rows,list) else []
    operators=set();consensus=set();attestkeys=set();providers=set();regions=set()
    total_power=0;powers=[]
    for index,op in enumerate(rows):
        if not isinstance(op,dict):
            errors.append(f"Operator {index}: invalid record");continue
        oid=op.get("operator_id")
        consensus_key=op.get("consensus_pubkey")
        public_pem=op.get("attestation_public_key_pem")
        signature=op.get("signature_base64")
        provider=op.get("infrastructure_provider")
        region=op.get("region")
        voting=op.get("genesis_voting_power")
        evidence=op.get("independence_evidence_url")
        need(isinstance(oid,str) and len(oid)>2 and oid not in operators,
             f"Operator {index}: unique operator ID required")
        need(isinstance(consensus_key,str) and len(consensus_key)>=40 and consensus_key not in consensus,
             f"Operator {index}: unique CometBFT consensus PUBLIC key required")
        need(isinstance(public_pem,str) and public_pem not in attestkeys and public_pem,
             f"Operator {index}: independent attestation public key required")
        if isinstance(oid,str): operators.add(oid)
        if isinstance(consensus_key,str): consensus.add(consensus_key)
        if isinstance(public_pem,str): attestkeys.add(public_pem)
        if isinstance(provider,str) and provider.strip():providers.add(provider)
        if isinstance(region,str) and region.strip():regions.add(region)
        need(isinstance(evidence,str) and urlsplit(evidence).scheme=="https"
             and bool(urlsplit(evidence).hostname),
             f"Operator {index}: third-party independence evidence URL missing")
        need(type(voting) is int and voting>0, f"Operator {index}: invalid voting power")
        if type(voting) is int and voting>0:
            powers.append(voting);total_power+=voting
        need(verify_ed25519(payload,public_pem,signature),
             f"Operator {index}: Ed25519 signature FAILED to verify")
    if total_power>0 and len(powers)==len(rows):
        need(all(3*p<total_power for p in powers),
             "An initial operator controls at least one third of voting power")
    need(len(providers)>=3, "At least three independent infrastructure providers required")
    need(len(regions)>=3, "At least three failure regions required")
    need(registry.get("operator_independence_audit_complete") is True,
         "Independent human/legal operator independence review is REQUIRED")
    need(registry.get("externally_audited_release") is True,
         "External production binary security audit is REQUIRED")
    return errors

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--genesis",required=True,type=Path)
    p.add_argument("--binary",required=True,type=Path)
    p.add_argument("--registry",required=True,type=Path)
    p.add_argument("--write-signing-payload",type=Path,
                   help="Export only PUBLIC deterministic payload for offline signoff; does NOT sign")
    args=p.parse_args()
    try:
        g=args.genesis.read_bytes(); b=args.binary.read_bytes()
        r=json.loads(args.registry.read_text(encoding="utf8"))
        if args.write_signing_payload:
            payload=canonical_payload(r["cosmos_chain_id"],r["evm_chain_id"],
                                     hashlib.sha256(g).hexdigest(),hashlib.sha256(b).hexdigest())
            if args.write_signing_payload.exists():
                raise ValueError("Cannot overwrite existing ceremony payload")
            args.write_signing_payload.write_bytes(payload)
            print("Review-only public ceremony payload created (no keys or signatures).")
            return 0
        errors=validate(r,g,b)
    except (ValueError,KeyError,OSError,TypeError,subprocess.CalledProcessError) as e:
        errors=[str(e)]
    if errors:
        print(f"GENESIS CEREMONY BLOCKED ({len(errors)}):",file=sys.stderr)
        for s in errors: print("- "+s,file=sys.stderr)
        return 1
    print("GENESIS PUBLIC ATTESTATIONS VALID. Independent signoffs, secure key custody and manual release authorization still REQUIRED.")
    return 0
if __name__=="__main__":raise SystemExit(main())
