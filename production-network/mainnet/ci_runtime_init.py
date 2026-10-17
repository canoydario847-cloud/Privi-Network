#!/usr/bin/env python3
"""Ephemeral CI-only PRVI candidate initialization test.

Runs the unapproved patched evmd binary with synthetic, disposable local
configuration, checks the *actual initialized app genesis parameters*, then
deletes everything. No funded genesis, mnemonic, transaction, production
validator, Railway deployment or public RPC endpoint is created.

This smoke test is NOT sufficient to prove production genesis correctness,
native supply invariants, or external audit approval.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

CID="privi-ci-nonproduction-999"
EID=999991
CAP=10**27
DEMO_DENOMS={"atest", "stake", "test", "TEST", "NOTE", "aphoton", "uatom"}


def inspect(genesis, expected_chain=CID):
    errors=[]
    def expect(ok, why):
        if not ok:
            errors.append(why)
    if not isinstance(genesis, dict):
        return ["Initialized genesis must be a JSON object"]
    expect(genesis.get("chain_id")==expected_chain, "Cosmos ID not bound to synthetic CI chain")
    state=genesis.get("app_state")
    if not isinstance(state,dict):
        return errors+["Missing initialized app_state"]
    evm=(state.get("evm") or {}).get("params") or {}
    staking=(state.get("staking") or {}).get("params") or {}
    mint=(state.get("mint") or {})
    mint_params=mint.get("params") or {}
    minter=mint.get("minter") or {}
    fee=(state.get("feemarket") or {}).get("params") or {}
    erc=(state.get("erc20") or {})
    expect(evm.get("evm_denom")=="aprvi", "EVM native gas must initialize as aprvi")
    options=evm.get("extended_denom_options") or {}
    expect(options.get("extended_denom")=="aprvi",
           "EVM extended native denom must initialize as aprvi")
    expect(staking.get("bond_denom")=="aprvi", "Staking bond denom must initialize as aprvi")
    expect(mint_params.get("mint_denom")=="aprvi", "Mint denom must initialize as aprvi")
    expect(str(minter.get("inflation")) in ("0", "0.0", "0.000000000000000000"),
           "Genesis mint inflation must initialize to zero")
    expect(fee.get("no_base_fee") is False, "EVM fee market must be enabled")
    expect(not erc.get("token_pairs"), "Upstream example ERC20 pairs must be removed")
    bank=state.get("bank") or {}
    md = bank.get("denom_metadata") or []
    native = [x for x in md if isinstance(x,dict) and x.get("base") == "aprvi"] if isinstance(md,list) else []
    expect(len(native) == 1, "Exactly one PRVI native bank denomination metadata entry required")
    if len(native) == 1:
        unit = native[0].get("denom_units") or []
        pairs = {(u.get("denom"), u.get("exponent")) for u in unit if isinstance(u,dict)}
        # JSON proto encoders may omit the zero exponent for the base denom.
        expect(native[0].get("display") == "prvi" and native[0].get("symbol") == "PRVI",
               "Native metadata must show prvi and PRVI")
        expect(("aprvi", 0) in {(name, int(exp or 0)) for name,exp in pairs}
               and ("prvi", 18) in {(name, int(exp or 0)) for name,exp in pairs},
               "Bank denom metadata must encode native 18-decimal PRVI")
    initial_supply=bank.get("supply") or []
    expect(isinstance(initial_supply,list), "Bank supply must be a list")
    if isinstance(initial_supply,list):
        try:
            expect(sum(int(c["amount"]) for c in initial_supply if c["denom"]=="aprvi") <= CAP,
                   "Native initial supply exceeds fixed cap")
            expect(not any(c.get("denom") in DEMO_DENOMS for c in initial_supply),
                   "Unapproved demo tokens found in initial bank supply")
        except (ValueError, KeyError, TypeError, AttributeError):
            errors.append("Initialized bank supply is malformed")
    return errors


def smoke(binary, destination):
    binary=Path(binary)
    if not binary.is_file() or not os.access(binary,os.X_OK):
        raise ValueError("Unapproved CI candidate executable required")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Refusing to overwrite any existing home/state")
    with tempfile.TemporaryDirectory(prefix="privi-ci-init-") as tmp:
        root=Path(tmp)
        home=root/"ephemeral-unfunded"
        env=os.environ.copy()
        env["HOME"]=str(root)
        cmd=[str(binary.resolve()), "--home", str(home),
             "init", "privi-ci-unfunded-disposable", "--chain-id", CID]
        # Do not reveal full subprocess output: some CLI versions log key material.
        out=subprocess.run(cmd, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60)
        if out.returncode != 0:
            # Only report a small allowlisted diagnostic, not raw CLI output
            # (some future CLI versions may print disposable key material).
            message=out.stderr.decode("utf-8",errors="replace")
            markers=("error:", "panic:", "unknown command", "unknown flag",
                     "failed", "invalid", "permission denied")
            candidates=[line.strip() for line in message.splitlines()
                        if any(word in line.lower() for word in markers)]
            reason="unclassified CLI failure (stderr intentionally redacted)"
            if candidates:
                safe=candidates[0]
                sensitive=("mnemonic","seed phrase","private key","password",
                           "passphrase","recovery phrase","secret key","0x")
                if not any(word in safe.lower() for word in sensitive):
                    safe=re.sub(r"/tmp/[A-Za-z0-9_./-]+","<CI_TEMP_PATH>",safe)
                    safe=re.sub(r"[0-9a-fA-F]{32,}","<REDACTED_HASH>",safe)
                    reason=safe[:350]
            raise ValueError(f"Nonproduction node init failed (exit {out.returncode}): {reason}")
        file=home/"config"/"genesis.json"
        if not file.is_file():
            raise ValueError("Initialized candidate did not create config/genesis.json")
        genesis=json.loads(file.read_text(encoding="utf-8"))
        errors=inspect(genesis)
        if errors:
            raise ValueError("Initialized PRVI candidate not ready: "+"; ".join(errors))
        result={
            "status":"SYNTHETIC_UNFUNDED_CI_INIT_ONLY",
            "synthetic_cosmos_chain_id":CID,
            "synthetic_evm_chain_id":EID,
            "inspected_genesis_sha256":hashlib.sha256(file.read_bytes()).hexdigest(),
            "native_gas_staking_fee_denom":"aprvi",
            "no_financial_mainnet_deployment":True,
            "keys_and_genesis_deleted_after_ci":True,
            "warning":"Synthetic init is not a 1-billion-token production genesis or live chain."
        }
        # Only save a summary; never persist or publish signing keys / genesis.
        with destination.open("x",encoding="utf-8") as f:
            json.dump(result,f,indent=2)
            f.write("\n")
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary",required=True,type=Path)
    p.add_argument("--report",required=True,type=Path)
    a=p.parse_args()
    try:
        data=smoke(a.binary,a.report)
    except (ValueError,OSError,subprocess.TimeoutExpired,TypeError) as exc:
        p.exit(1,"PRVI CI RUNTIME INIT BLOCKED: "+str(exc)+"\n")
    print(json.dumps(data,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
