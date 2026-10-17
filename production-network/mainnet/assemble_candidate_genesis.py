#!/usr/bin/env python3
"""Compose an OFFLINE, UNAPPROVED PRVI candidate genesis from fully reviewed public inputs.

Creates JSON candidate only. No account keys, validators, transactions, coins,
network, financial release, or RPC deployment. Refuses unknown chain IDs,
demo balances, missing allocation ownership and missing vesting periods.
"""
import argparse
import copy
import json
import re
import sys
from datetime import datetime,timezone
from pathlib import Path

try:
    from validate_candidate_genesis import errors_for, CATEGORIES, CAP
except ImportError:
    from importlib.util import spec_from_file_location, module_from_spec
    spec=spec_from_file_location("validate_candidate_genesis",
        Path(__file__).with_name("validate_candidate_genesis.py"))
    v=module_from_spec(spec);spec.loader.exec_module(v)
    errors_for,CATEGORIES,CAP=v.errors_for,v.CATEGORIES,v.CAP

PROTECTED={"contributors","ecosystem_development","protocol_treasury"}
ADDRESS=re.compile(r"^privi1[023456789acdefghjklmnpqrstuvwxyz]{38,80}$")
DEMO_CHAINS={"local-4221","privi-dev-1"}
DEMO_EVM_IDS={262144,4221,56,97,1}

BECH32_CHARS="qpzry9x8gf2tvdw0s3jn54khce6mua7l"
def bech32_polymod(values):
    result=1
    for value in values:
        top=result>>25
        result=((result&0x1ffffff)<<5)^value
        for j,gen in enumerate((0x3b6a57b2,0x26508e6d,0x1ea119fa,0x3d4233dd,0x2a1462b3)):
            if (top>>j)&1:result^=gen
    return result

def valid_privi_account(address):
    """Validate a 20-byte Privi Bech32 (not Bech32m) account checksum."""
    if not isinstance(address,str) or len(address)!=(len("privi1")+38) or not address.startswith("privi1"):
        return False
    try:data=[BECH32_CHARS.index(char) for char in address[6:]]
    except ValueError:return False
    if bech32_polymod([ord(x)>>5 for x in "privi"]+[0]+[ord(x)&31 for x in "privi"]+data)!=1:
        return False
    # Cosmos EVM public accounts are 20 bytes = 32 5-bit groups plus 6 checksum symbols.
    acc=0;bits=0;out=[]
    for x in data[:-6]:
        acc=(acc<<5)|x
        bits+=5
        if bits>=8:
            bits-=8
            out.append((acc>>bits)&255)
    return len(out)==20 and (bits==0 or (acc&((1<<bits)-1))==0)

EXPECTED_CATEGORIES=set(CATEGORIES)

class NotReady(ValueError):
    pass

def positive_decimal(s,allow_zero=False):
    if not isinstance(s,str) or not s.isdecimal():
        raise NotReady("Every base denomination amount/epoch must be an integer string")
    i=int(s)
    if i<0 or (not allow_zero and i==0):
        raise NotReady("Amounts and vesting durations must be positive")
    return i

def validate_input(template, ledger, config, genesis_unix):
    n=config.get("network",{})
    cid=n.get("cosmos_chain_id")
    eid=n.get("evm_chain_id")
    if not isinstance(cid,str) or not re.fullmatch(r"privi-[a-z0-9-]{5,55}",cid) or cid in DEMO_CHAINS:
        raise NotReady("Independent reviewer must assign unique non-demo Cosmos chain ID")
    if type(eid) is not int or eid<1000 or eid in DEMO_EVM_IDS:
        raise NotReady("Independent reviewer must assign unique non-demo numeric EVM chain ID")
    if config.get("status")!="DESIGN_ONLY_NOT_A_GENESIS":
        raise NotReady("Only a design-stage configuration is accepted")
    if config.get("coin",{}).get("max_supply_base_units")!=str(CAP):
        raise NotReady("Proposed native PRVI supply cap mismatch")
    if template.get("chain_id") not in ("",None,cid):
        raise NotReady("Base genesis is for a different chain; refuse conversion")
    if not isinstance(genesis_unix,int) or genesis_unix<1_700_000_000:
        raise NotReady("Explicit future, independently approved genesis Unix time required")
    app=template.get("app_state")
    if not isinstance(app,dict):
        raise NotReady("Template has no complete Cosmos EVM app_state")
    required=("bank","auth","mint","staking","slashing","evm","feemarket","erc20","genutil")
    if any(not isinstance(app.get(k),dict) for k in required):
        raise NotReady("Base genesis must contain complete required Cosmos EVM module states")
    if (app["bank"].get("balances") or app["bank"].get("supply") or
            app["auth"].get("accounts") or app["genutil"].get("gen_txs")):
        raise NotReady("Base genesis already has accounts/supply/gentxs; never overwrite unknown genesis")
    if template.get("validators"):
        raise NotReady("Base genesis has existing validator consensus records")
    rows=ledger.get("allocations")
    if not isinstance(rows,list) or len(rows)<5:
        raise NotReady("Public allocations ledger must be completed by human review")

    owners=set(); totals={x:0 for x in EXPECTED_CATEGORIES}
    for row in rows:
        if not isinstance(row,dict):
            raise NotReady("Malformed allocation record")
        cat=row.get("category")
        if cat not in EXPECTED_CATEGORIES:
            raise NotReady(f"Unknown allocation category: {cat}")
        address=row.get("address")
        if not valid_privi_account(address):
            raise NotReady("Expected reviewed privi1 public address (no private key)")
        if address in owners:
            raise NotReady("Repeated allocation recipient; consolidate BEFORE signing")
        owners.add(address)
        amt=positive_decimal(row.get("amount_base_units"))
        totals[cat]+=amt
        if cat in PROTECTED:
            periods=row.get("vesting_periods")
            if not isinstance(periods,list) or not periods:
                raise NotReady(f"Missing on-chain vesting periods for {cat} {address}")
            if sum(positive_decimal(p.get("amount_base_units")) for p in periods)!=amt:
                raise NotReady(f"Vesting amounts do not match {cat} allocation")
            if sum(positive_decimal(p.get("length_seconds")) for p in periods)>40*365*86400:
                raise NotReady("Excessive proposed vesting duration")
            start=positive_decimal(row.get("vesting_start_unix"))
            if start<genesis_unix or start>genesis_unix+365*86400:
                raise NotReady("Vesting start time must be within one year of approved genesis")
        elif row.get("vesting_periods"):
            raise NotReady("Nonprotected accounts require explicit separate review to add vesting")
    if totals!=CATEGORIES or sum(totals.values())!=CAP:
        raise NotReady("All five allocation bucket totals must match the approved 1B PRVI policy")
    return cid,eid

def assemble(template,ledger,config,genesis_unix):
    cid,_=validate_input(template,ledger,config,genesis_unix)
    gen=copy.deepcopy(template)
    state=gen["app_state"]
    gen["chain_id"]=cid
    gen["genesis_time"]=datetime.fromtimestamp(genesis_unix,timezone.utc).isoformat().replace("+00:00","Z")
    gen["validators"]=[]
    gen["consensus_params"]=gen.get("consensus_params") or {}
    coin=lambda amt:[{"denom":"aprvi","amount":str(amt)}]
    auth=[]
    balances=[]
    for row in sorted(ledger["allocations"],key=lambda x:x["address"]):
        addr=row["address"]
        amt=row["amount_base_units"]
        base={"address":addr,"pub_key":None,"account_number":"0","sequence":"0"}
        if row["category"] in PROTECTED:
            start=int(row["vesting_start_unix"])
            periods=[{"length":str(p["length_seconds"]),"amount":coin(p["amount_base_units"])}
                     for p in row["vesting_periods"]]
            end=start+sum(int(p["length_seconds"]) for p in row["vesting_periods"])
            account={
               "@type":"/cosmos.vesting.v1beta1.PeriodicVestingAccount",
               "base_vesting_account":{
                   "base_account":base,
                   "original_vesting":coin(amt),
                   "delegated_free":[],
                   "delegated_vesting":[],
                   "end_time":str(end)
               },
               "start_time":str(start),
               "vesting_periods":periods
            }
        else:account={"@type":"/cosmos.auth.v1beta1.BaseAccount",**base}
        auth.append(account)
        balances.append({"address":addr,"coins":coin(amt)})
    state["auth"]["accounts"]=auth
    state["bank"]["balances"]=balances
    state["bank"]["supply"]=coin(CAP)
    metadata=[x for x in state["bank"].get("denom_metadata",[]) if x.get("base")!="aprvi"]
    if metadata:
        # App template with unrelated token metadata needs full review. No implicit conversion.
        raise NotReady("Upstream bank denomination metadata is non-empty; inspect before genesis build")
    metadata.append({"description":"Native fee and staking coin for Privi blockchain",
                     "denom_units":[{"denom":"aprvi","exponent":0},
                                    {"denom":"prvi","exponent":18}],
                     "base":"aprvi","display":"prvi","name":"Privi","symbol":"PRVI"})
    state["bank"]["denom_metadata"]=metadata

    state["staking"].setdefault("params",{}).update({
       "bond_denom":"aprvi",
       "unbonding_time":"1814400s",
       "max_validators":config["staking"]["max_validators"],
       "min_commission_rate":config["staking"]["min_commission_rate"]
    })
    state["slashing"].setdefault("params",{}).update({
       "slash_fraction_double_sign":config["staking"]["double_sign_slash_fraction"],
       "slash_fraction_downtime":config["staking"]["downtime_slash_fraction"]
    })
    state["mint"].setdefault("params",{})["mint_denom"]="aprvi"
    state["mint"].setdefault("minter",{})["inflation"]="0.000000000000000000"
    state["evm"].setdefault("params",{}).update({
       "evm_denom":"aprvi","extended_denom_options":{"extended_denom":"aprvi"}
    })
    state["erc20"]["token_pairs"]=[]
    state["erc20"]["native_precompiles"]=[]
    state["feemarket"].setdefault("params",{})["no_base_fee"]=False
    # Note: NO validator gentxs, no signatures and no funded network are created.
    state["genutil"]["gen_txs"]=[]
    failures=errors_for(gen,ledger,config)
    if failures:
        raise NotReady("Candidate genesis failed structural review: "+"; ".join(failures))
    return gen

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--empty-upstream-template",required=True,type=Path)
    p.add_argument("--approved-public-ledger",required=True,type=Path)
    p.add_argument("--config",required=True,type=Path)
    p.add_argument("--genesis-unix",required=True,type=int)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise NotReady("Will not overwrite existing candidate genesis file")
        template=json.loads(args.empty_upstream_template.read_text())
        ledger=json.loads(args.approved_public_ledger.read_text())
        config=json.loads(args.config.read_text())
        result=assemble(template,ledger,config,args.genesis_unix)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open("x",encoding="utf8") as f:
            json.dump(result,f,sort_keys=True,indent=2)
            f.write("\n")
        print("OFFLINE UNAPPROVED PRVI CANDIDATE JSON GENERATED; NOT A SIGNED GENESIS.")
        print("Add audited genesis gentxs, operator public keys and signatures only through a separate reviewed ceremony.")
        return 0
    except (NotReady,OSError,ValueError,KeyError,TypeError,OverflowError) as e:
        print("CANDIDATE GENESIS NOT CREATED:",str(e),file=sys.stderr)
        return 1
if __name__=="__main__":raise SystemExit(main())
