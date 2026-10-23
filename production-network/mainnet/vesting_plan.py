#!/usr/bin/env python3
"""Produce review-only Cosmos PeriodicVestingAccount drafts from APPROVED input.

Does not generate addresses, coin balances, genesis, transactions or PRVI.
Never use placeholder wallet addresses or a CI output as funded mainnet genesis.
"""
import argparse
import calendar
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from bech32_accounts import valid_privi_address

CAP=10**27
BUCKETS={"community_adoption":40*10**25,"ecosystem_development":20*10**25,
         "staking_reward_reserve":20*10**25,"protocol_treasury":10*10**25,
         "contributors":10*10**25}
SENSITIVE={"ecosystem_development","protocol_treasury","contributors"}
ATOM=10**18

def plus_months(dt,n):
    y=dt.year+(dt.month-1+n)//12
    m=(dt.month-1+n)%12+1
    d=min(dt.day,calendar.monthrange(y,m)[1])
    return dt.replace(year=y,month=m,day=d)

def valid_amount(raw):
    if type(raw) is not str or not re.fullmatch(r"[1-9][0-9]*",raw):
        raise ValueError("all amounts must be positive, canonical integer strings")
    return int(raw)

def plan(ledger, genesis_unix, months_cliff=12, months_unlock=36):
    if type(genesis_unix) is not int or not (int(datetime.now(timezone.utc).timestamp()) < genesis_unix <= 4_102_444_800):
        raise ValueError("independently reviewed future genesis Unix timestamp required")
    if months_cliff!=12 or months_unlock!=36:
        raise ValueError("approved contributor schedule is 12-month cliff plus 36 monthly unlocks")
    rows=ledger.get("allocations") if isinstance(ledger,dict) else None
    if not isinstance(rows,list) or not rows:
        raise ValueError("complete, approved allocations ledger required")
    total_by_bucket={key:0 for key in BUCKETS}
    seen=set()
    vesting=[]
    start=datetime.fromtimestamp(genesis_unix,timezone.utc)
    for i,row in enumerate(rows):
        if not isinstance(row,dict):
            raise ValueError("invalid allocation row")
        category=row.get("category")
        addr=row.get("address")
        if category not in BUCKETS:
            raise ValueError(f"unrecognized allocation category at index {i}")
        # Check canonical lowercase Bech32 checksum and 20-byte account payload.
        if not isinstance(addr,str) or not valid_privi_address(addr):
            raise ValueError(f"address at row {i} failed Bech32 checksum validation")
        if addr in seen:
            raise ValueError("recipient duplicated across category ledger")
        seen.add(addr)
        amount=valid_amount(row.get("amount_base_units"))
        total_by_bucket[category]+=amount
        if category not in SENSITIVE:
            continue
        if row.get("schedule") != ("contributor_12_plus_36_months" if category=="contributors" else "monthly_36_months"):
            raise ValueError(f"missing explicit reviewed vesting schedule for {category}")
        periods=[]
        cursor=start
        steps=36
        per,extra=divmod(amount,steps)
        if per==0:
            raise ValueError("amount too small for positive 36-period vesting")
        for j in range(steps):
            month_index=(13+j) if category=="contributors" else (1+j)
            nxt=plus_months(start,month_index)
            seconds=int((nxt-cursor).total_seconds())
            value=per+(extra if j==steps-1 else 0)
            if seconds<=0 or value<=0:
                raise ValueError("invalid vesting increment")
            periods.append({"length":str(seconds),"amount":[{"denom":"aprvi","amount":str(value)}]})
            cursor=nxt
        vesting.append({
            "category":category,"address":addr,
            "account":{
                "@type":"/cosmos.vesting.v1beta1.PeriodicVestingAccount",
                "base_vesting_account":{
                    "base_account":{"address":addr,"pub_key":None,"account_number":"0","sequence":"0"},
                    "original_vesting":[{"denom":"aprvi","amount":str(amount)}],
                    "delegated_free":[],"delegated_vesting":[],"end_time":str(int(cursor.timestamp()))
                },
                "start_time":str(genesis_unix),"vesting_periods":periods
            }
        })
    if total_by_bucket!=BUCKETS or sum(total_by_bucket.values())!=CAP:
        raise ValueError(f"genesis allocation totals MUST equal five exact PRVI policy buckets: {total_by_bucket}")
    return {"status":"DRAFT_ACCOUNTS_FOR_REVIEW_NOT_GENESIS",
            "genesis_time_unix":genesis_unix,
            "max_supply_aprvi":str(CAP),
            "allocation_categories":{k:str(v) for k,v in total_by_bucket.items()},
            "vesting_accounts":vesting,
            "warnings":["Externally verify every Bech32 checksum and recipient's beneficial owner.",
                        "Review exact Cosmos EVM protobuf compatibility and cap enforcement.",
                        "Construct bank balances, auth accounts, and genesis OFFLINE under approved ceremony.",
                        "No funds, signing keys, or tokens are generated by this tool."]}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-ledger",type=Path,required=True)
    parser.add_argument("--genesis-time",type=int,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("refusing to overwrite a previous review artifact")
    try:
        doc=plan(json.loads(args.approved_ledger.read_text()),args.genesis_time)
    except (ValueError,TypeError,OSError,OverflowError) as exc:
        parser.error(str(exc))
    args.output.write_text(json.dumps(doc,indent=2)+"\n")
    print("DRAFT VESTING ACCOUNTS GENERATED. NOT A GENESIS OR RELEASE AUTHORIZATION.")
    return 0

if __name__=="__main__":raise SystemExit(main())
