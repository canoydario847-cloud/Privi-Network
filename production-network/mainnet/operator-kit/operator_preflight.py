#!/usr/bin/env python3
"""Read-only checks for ONE separately controlled Privi mainnet validator+sentry.

Never generates, opens, displays, copies, signs with, or submits private keys.
Successful static checks alone NEVER authorize blockchain financial activation.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tomllib
from pathlib import Path

MAX_NATIVE=10**27
DENOM="aprvi"
DEMO_COSMOS={"local-4221","privi-dev-1"}
DEMO_EVM={262144,4221,56,97,1}
IMAGE=re.compile(r"^[a-z0-9][a-z0-9._/-]*(?::[a-z0-9._-]+)?@sha256:[a-f0-9]{64}$")
HASH=re.compile(r"^[a-f0-9]{64}$")

def sha256(path):
    d=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            d.update(chunk)
    return d.hexdigest()

def verify(state_root, expected_genesis_sha, cosmos_chain_id, evm_chain_id, image_ref):
    """Return errors, never secret contents. Does not contact RPC or mutate files."""
    failures=[]
    def need(ok,reason):
        if not ok: failures.append(reason)
    need(isinstance(cosmos_chain_id,str) and bool(re.fullmatch(r"privi-[a-z0-9-]{5,55}",cosmos_chain_id))
         and cosmos_chain_id not in DEMO_COSMOS,
         "production Cosmos chain ID must be approved and non-demo")
    need(type(evm_chain_id) is int and evm_chain_id>1000 and evm_chain_id not in DEMO_EVM,
         "production EVM chain ID must be reviewed and different from TEST and BNB")
    need(isinstance(expected_genesis_sha,str) and bool(HASH.fullmatch(expected_genesis_sha))
         and expected_genesis_sha != "0"*64,"approved genesis SHA-256 required")
    need(isinstance(image_ref,str) and bool(IMAGE.fullmatch(image_ref))
         and not image_ref.startswith("cosmos/evmd"),
         "candidate node container image must be pinned by immutable reviewed sha256 digest")
    nodes={}
    for label in ("validator","sentry"):
        home=state_root/(label+"-state")
        if not home.is_dir() or home.is_symlink():
            failures.append(f"{label} state directory missing or symlinked")
            continue
        mode=stat.S_IMODE(home.stat().st_mode)
        need(mode&0o077==0,f"{label} state directory is readable by group/others")
        config=home/"config"
        if not config.is_dir() or config.is_symlink():
            failures.append(f"{label} config directory missing or symlinked")
            continue
        paths={key:config/file for key,file in (
            ("genesis","genesis.json"),("nodekey","node_key.json"),
            ("comet","config.toml"),("app","app.toml")
        )}
        if label=="validator":
            paths["signer"]=config/"priv_validator_key.json"
        else:
            need(not (config/"priv_validator_key.json").exists(),
                 "sentry must not hold ANY validator signing key")
        if any(not p.is_file() or p.is_symlink() for p in paths.values()):
            failures.append(f"{label} missing or symlinked genesis/node/config files; initialize privately")
            continue
        for key,path in paths.items():
            # All validator data and key files should be readable only by operator.
            if key in ("nodekey","signer"):
                need(stat.S_IMODE(path.stat().st_mode)&0o077==0,
                     f"{label} {key} permission permits group/other access")
        hashval=sha256(paths["genesis"])
        need(hashval==expected_genesis_sha,
             f"{label} genesis SHA-256 does not match independently approved hash")
        try:
            genesis=json.loads(paths["genesis"].read_text(encoding="utf8"))
            need(genesis.get("chain_id")==cosmos_chain_id,
                 f"{label} genesis Cosmos chain ID mismatch")
            state=genesis.get("app_state") or {}
            bank=state.get("bank") or {}
            supply=bank.get("supply",[])
            native=sum(int(c.get("amount","0")) for c in supply if c.get("denom")==DENOM)
            need(native==MAX_NATIVE,f"{label} genesis PRVI bank supply must equal fixed 10^27 base units")
            need(not any(c.get("denom") in ("atest","TEST","NOTE","aatom","stake")
                         for c in supply), f"{label} genesis contains demo TEST coin supply")
            need(((state.get("staking") or {}).get("params") or {}).get("bond_denom")==DENOM,
                 f"{label} genesis staking bond denom must be aprvi")
            need(((state.get("evm") or {}).get("params") or {}).get("evm_denom")==DENOM,
                 f"{label} genesis EVM fee denom must be aprvi")
        except (ValueError,TypeError,AttributeError,KeyError):
            failures.append(f"{label} genesis is malformed or nonnumeric")
        try:
            comet=tomllib.loads(paths["comet"].read_text(encoding="utf8"))
            app=tomllib.loads(paths["app"].read_text(encoding="utf8"))
            p2p=comet.get("p2p",{})
            need(p2p.get("persistent_peers", "").strip()!="",
                 f"{label} P2P persistent peers must be configured")
            if label=="validator":
                need(p2p.get("pex") is False,"validator PEX must be disabled (private sentry topology)")
                need(p2p.get("private_peer_ids","").strip()!="",
                     "validator private sentry peer IDs missing")
            else:
                need(p2p.get("pex") is True, "public sentry PEX should be enabled")
            need(str((comet.get("rpc") or {}).get("laddr","")).startswith("tcp://127.0.0.1:"),
                 f"{label} Comet RPC must bind loopback only")
            need(((app.get("json-rpc") or {}).get("enable")) is False,
                 f"{label} EVM JSON-RPC must be disabled on signing/sentry nodes")
            gas=app.get("minimum-gas-prices")
            need(isinstance(gas,str) and gas.endswith(DENOM) and gas!="0aprvi",
                 f"{label} app.toml minimum-gas-prices must be reviewed nonzero aprvi")
        except (OSError,ValueError,TypeError,AttributeError):
            failures.append(f"{label} node TOML malformed")
        nodes[label]=paths

    if "validator" in nodes and "sentry" in nodes:
        need(sha256(nodes["validator"]["nodekey"])!=sha256(nodes["sentry"]["nodekey"]),
             "validator and sentry must have DIFFERENT P2P node keys")
    need(not (state_root/"operator-state").exists(),
         "unexpected legacy node state could contain stale signing history")
    return failures

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state-root",required=True,type=Path,help="Privately initialized operator directory")
    p.add_argument("--approved-genesis-sha256",required=True)
    p.add_argument("--cosmos-chain-id",required=True)
    p.add_argument("--evm-chain-id",required=True,type=int)
    p.add_argument("--image-ref",required=True)
    args=p.parse_args()
    problems=verify(args.state_root,args.approved_genesis_sha256,
                    args.cosmos_chain_id,args.evm_chain_id,args.image_ref)
    if problems:
        print(f"OPERATOR START BLOCKED: {len(problems)} failures",file=sys.stderr)
        for x in problems: print("- "+x,file=sys.stderr)
        return 1
    print("OPERATOR STATIC PRECHECK PASS. Independent genesis/key audit and manual approval still required.")
    print("This tool cannot verify chain liveness, validator independence, signatures, or supply at runtime.")
    return 0

if __name__=="__main__":raise SystemExit(main())
