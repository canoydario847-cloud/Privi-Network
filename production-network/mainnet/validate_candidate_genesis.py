#!/usr/bin/env python3
"""Fail-closed review of candidate PRVI genesis JSON and disclosed allocation ledger.

This validator is not a genesis constructor or a financial mainnet authorization.
It never creates wallets, txs, genesis, nodes, or coins.
"""
import argparse
import decimal
import json
import sys
from collections import Counter
from pathlib import Path

D=decimal.Decimal
CAP=10**27
CATEGORIES={
    "community_adoption":400_000_000*10**18,
    "ecosystem_development":200_000_000*10**18,
    "staking_reward_reserve":200_000_000*10**18,
    "protocol_treasury":100_000_000*10**18,
    "contributors":100_000_000*10**18
}
ZERO_TEST_DENOMS={"atest","test","TEST","stake","uatom","aatom","NOTE","priv"}

def errors_for(genesis, allocations, config):
    errors=[]
    def need(ok,why):
        if not ok:errors.append(why)
    def getmap(parent, key):
        v=parent.get(key) if isinstance(parent,dict) else None
        if not isinstance(v,dict):
            errors.append(f"Missing required section: {key}")
            return {}
        return v
    def exact_int(v):
        if type(v) is not str or not v.isdecimal():
            raise ValueError("amount must be a nonnegative integer string")
        return int(v)
    def coin_amount(coins, denom="aprvi", allow_other=False):
        total=0
        if not isinstance(coins,list):
            raise ValueError("coins must be a list")
        seen=set()
        for c in coins:
            if not isinstance(c,dict):
                raise ValueError("coin entry must be object")
            d=c.get("denom")
            if d in seen:
                raise ValueError("repeated coin denomination")
            seen.add(d)
            if d!=denom and (not allow_other or d in ZERO_TEST_DENOMS):
                raise ValueError(f"Unexpected coin denomination {d}")
            if d==denom:total+=exact_int(c.get("amount"))
        return total

    need(genesis.get("chain_id")==config.get("network",{}).get("cosmos_chain_id")
         and isinstance(genesis.get("chain_id"),str)
         and genesis.get("chain_id") not in ("local-4221","privi-dev-1"),
         "Fresh independently reviewed Cosmos chain ID does not match genesis")
    need(config.get("coin",{}).get("max_supply_base_units")==str(CAP),
         "Native PRVI cap metadata mismatch")
    state=getmap(genesis,"app_state")
    bank=getmap(state,"bank")
    auth=getmap(state,"auth")
    stake=getmap(state,"staking")
    slashing=getmap(state,"slashing")
    evm=getmap(state,"evm")
    mint=getmap(state,"mint")
    erc20=getmap(state,"erc20")
    feemarket=getmap(state,"feemarket")
    try:
        supply=coin_amount(bank.get("supply",[]))
        need(supply==CAP,"Bank native supply not equal to EXACT fixed 1 billion PRVI cap")
        bals=bank.get("balances",[])
        need(isinstance(bals,list),"Bank balances must be a list")
        actual={}
        for row in bals if isinstance(bals,list) else []:
            addr=row.get("address")
            if not isinstance(addr,str) or not addr.startswith("privi1") or addr in actual:
                raise ValueError("missing, malformed, or duplicated privi bech32 account address")
            amount=coin_amount(row.get("coins",[]))
            need(amount>0,f"Genesis zero balance for {addr}")
            actual[addr]=amount
        need(sum(actual.values())==CAP,"Bank balances and supply do not reconcile exactly")
    except (ValueError,AttributeError,TypeError) as e:
        errors.append(f"Invalid bank native supply or balance: {e}")
        actual={}

    accounts=auth.get("accounts",[])
    need(isinstance(accounts,list) and len(accounts)>0,"Genesis auth accounts missing")
    auth_by_address={}
    if isinstance(accounts,list):
        for i,a in enumerate(accounts):
            if not isinstance(a,dict):
                errors.append(f"Malformed auth account {i}");continue
            kind=a.get("@type","")
            if kind=="/cosmos.auth.v1beta1.BaseAccount":
                addr=a.get("address")
            elif kind=="/cosmos.vesting.v1beta1.PeriodicVestingAccount":
                addr=((a.get("base_vesting_account") or {}).get("base_account") or {}).get("address")
            else:
                errors.append(f"Unapproved account type at index {i}: {kind}");continue
            if addr in auth_by_address or not isinstance(addr,str):
                errors.append(f"Missing or duplicate auth address {addr}");continue
            auth_by_address[addr]=a
    need(set(actual)==set(auth_by_address),"Bank allocation recipients and auth accounts differ")

    record=allocations.get("allocations")
    if not isinstance(record,list) or not record:
        errors.append("Allocation ledger missing");record=[]
    seen=set();totals=Counter()
    for i,row in enumerate(record):
        if not isinstance(row,dict):
            errors.append(f"Malformed allocation {i}");continue
        group=row.get("category")
        addr=row.get("address")
        if group not in CATEGORIES:errors.append(f"Unapproved allocation category: {group}")
        if not isinstance(addr,str) or addr in seen:
            errors.append(f"Duplicate or invalid allocation recipient: {addr}");continue
        seen.add(addr)
        try:
            amount=exact_int(row.get("amount_base_units"))
            need(amount>0,f"Allocation {i} cannot be zero")
        except ValueError as exc:
            errors.append(f"Invalid allocation amount: {exc}");continue
        totals[group]+=amount
        need(actual.get(addr)==amount,
             f"Ledger amount not equal to bank balance for {addr}")
        if group in ("contributors","ecosystem_development","protocol_treasury"):
            acct=auth_by_address.get(addr,{})
            need(acct.get("@type")=="/cosmos.vesting.v1beta1.PeriodicVestingAccount",
                 f"Sensitive allocation {group} must use reviewed on-chain PeriodicVestingAccount")
            if acct.get("@type")=="/cosmos.vesting.v1beta1.PeriodicVestingAccount":
                base=acct.get("base_vesting_account") or {}
                try:
                    original=coin_amount(base.get("original_vesting",[]))
                    periods=acct.get("vesting_periods",[])
                    if not isinstance(periods,list) or not periods:raise ValueError("missing vesting periods")
                    amounts=[coin_amount(p.get("amount",[])) for p in periods]
                    lengths=[exact_int(str(p.get("length"))) for p in periods]
                    need(all(x>0 for x in amounts),"Vesting periods must vest positive PRVI amounts")
                    need(all(x>0 for x in lengths),"Vesting period lengths must be positive")
                    start=exact_int(str(acct.get("start_time")))
                    end=exact_int(str(base.get("end_time")))
                    need(sum(amounts)==original==amount,"Vesting sum must equal original allocated PRVI")
                    need(start+sum(lengths)==end,"Vesting periods must reconcile to account end time")
                    need(coin_amount(base.get("delegated_free",[]))==0 and
                         coin_amount(base.get("delegated_vesting",[]))==0,
                         "No genesis-delegated vesting tokens in initial candidate")
                except (ValueError,AttributeError,TypeError) as exc:
                    errors.append(f"Invalid on-chain vesting account {addr}: {exc}")
    need(seen==set(actual),"Allocation ledger differs from bank recipient set")
    for group,amount in CATEGORIES.items():
        need(totals[group]==amount,f"{group} must allocate exactly {amount} aprvi")
    need(sum(totals.values())==CAP,"Ledger categories must sum to exact total cap")

    params=getmap(stake,"params")
    sconf=config.get("staking",{})
    need(params.get("bond_denom")=="aprvi","Staking bond denom must be aprvi")
    need(str(params.get("max_validators"))==str(sconf.get("max_validators")),
         "Staking max_validators mismatch")
    need(str(params.get("min_commission_rate"))==str(sconf.get("min_commission_rate")),
         "Staking minimum commission mismatch")
    # Cosmos protobuf JSON duration format uses seconds, not bare hours.
    need(str(params.get("unbonding_time"))=="1814400s",
         "Staking unbonding time must be 21 days = 1814400s")
    slp=getmap(slashing,"params")
    for field,want in (("slash_fraction_double_sign","double_sign_slash_fraction"),
                       ("slash_fraction_downtime","downtime_slash_fraction")):
        try:
            got=D(str(slp.get(field)))
            expected=D(sconf.get(want))
            need(got==expected, f"Slashing {field} mismatch")
        except (decimal.InvalidOperation,TypeError,ValueError):
            errors.append(f"Invalid slashing parameter {field}")
    ep=getmap(evm,"params")
    need(ep.get("evm_denom")=="aprvi","EVM native fee denom must be aprvi")
    try:
        ext=ep.get("extended_denom_options") or {}
        need(ext.get("extended_denom")=="aprvi","EVM extended denom must be aprvi")
    except AttributeError:errors.append("EVM extended denom options invalid")
    mp=getmap(mint,"params")
    need(mp.get("mint_denom")=="aprvi","Mint module denom must remain native aprvi")
    minter=getmap(mint,"minter")
    try:
        need(D(str(minter.get("inflation")))==0,
             "x/mint genesis inflation must be zero as defense in depth")
    except (decimal.InvalidOperation,TypeError,ValueError):
        errors.append("Invalid mint genesis inflation")
    need(not erc20.get("token_pairs"),"Upstream demo ERC20 token pairs prohibited")
    fp=getmap(feemarket,"params")
    need(fp.get("no_base_fee") is False,"Production EVM must not disable fee market by default")

    for md in bank.get("denom_metadata",[]):
        if md.get("base")=="aprvi":
            units=md.get("denom_units",[])
            want={("aprvi",0),("prvi",18)}
            got={(u.get("denom"),int(u.get("exponent",0))) for u in units}
            need(want.issubset(got),"PRVI denom metadata must expose 18-decimal display unit")
            need(md.get("display")=="prvi","Native display denom metadata must be prvi")
            break
    else:
        errors.append("Missing native PRVI bank denomination metadata")

    # Audited 7-operator genesis + signing evidence is checked by separate
    # mainnet_preflight. These structural checks never authorize mainnet.
    return errors

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--genesis",required=True,type=Path)
    p.add_argument("--allocations",required=True,type=Path)
    p.add_argument("--config",type=Path,default=Path(__file__).with_name("privi_chain_config.json"))
    args=p.parse_args()
    try:
        genesis=json.loads(args.genesis.read_text(encoding="utf8"))
        allocations=json.loads(args.allocations.read_text(encoding="utf8"))
        cfg=json.loads(args.config.read_text(encoding="utf8"))
        errs=errors_for(genesis,allocations,cfg)
    except (ValueError,OSError,AttributeError,TypeError) as exc:
        errs=[str(exc)]
    if errs:
        print(f"CANDIDATE GENESIS REJECTED ({len(errs)}):",file=sys.stderr)
        for error in errs:print(" - "+error,file=sys.stderr)
        return 1
    print("CANDIDATE STRUCTURAL CHECKS PASS; INDEPENDENT AUDIT/GENESIS SIGNOFF STILL REQUIRED.")
    return 0

if __name__=="__main__":raise SystemExit(main())
