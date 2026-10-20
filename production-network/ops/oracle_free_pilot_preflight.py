#!/usr/bin/env python3
"""Static NO-SPEND review of an Oracle Always Free valueless Privi pilot.

Not an OCI provisioning client. Never uses credentials or sends a cloud request.
Limits from Oracle Always Free docs updated June 2026: A1 2 OCPU / 12GB,
200GB total block storage, home region only.
"""
import argparse
import json
import re
from pathlib import Path

ALLOWED_TOP = {"schema_version","provider","phase","resource_tier","owner",
 "financial_network_enabled","real_prvi_issuance_enabled",
 "instance_provisioning_enabled","billing_upgrade_authorized","region","nodes"}
ALLOWED_NODE = {"id","shape","architecture","ocpus","memory_gb",
 "boot_volume_gb","operating_system","host_type","public_rpc_exposed",
 "public_ssh_exposed","fee_denom","creates_production_consensus_keys"}
ALLOWED_ID = re.compile(r"^privi-free-dev-[0-9]{2}$")
SECRET = re.compile(r"(secret|private.?key|password|mnemonic|token|credential|seed.?phrase|api.?key)",re.I)

def unique_keys(items):
    d={}
    for k,v in items:
        if k in d:
            raise ValueError(f"duplicate JSON key: {k}")
        d[k]=v
    return d

def assess(obj):
    errors=[]
    if not isinstance(obj,dict):
        return ["pilot must be an object"]
    unknown=set(obj)-ALLOWED_TOP
    missing=ALLOWED_TOP-set(obj)
    if unknown or missing:
        errors.append(f"invalid top-level fields: unexpected={sorted(unknown)}, missing={sorted(missing)}")
    for k in obj:
        if SECRET.search(k):
            errors.append("secret-like field name is forbidden")
    expected={
      "schema_version":1,
      "provider":"oracle-oci",
      "phase":"valueless-privi-build-and-observation",
      "resource_tier":"Always Free",
      "owner":"Privi World Corp",
      "financial_network_enabled":False,
      "real_prvi_issuance_enabled":False,
      "instance_provisioning_enabled":False,
      "billing_upgrade_authorized":False,
      "region":"UNASSIGNED",
    }
    for k,v in expected.items():
        if type(obj.get(k)) is not type(v) or obj.get(k)!=v:
            errors.append(f"nonfinancial/no-spend draft requires {k}={v!r}")
    nodes=obj.get("nodes")
    if not isinstance(nodes,list) or not 1<=len(nodes)<=2:
        errors.append("one or two Oracle Always Free A1 VMs only; four host production topology is impossible under this allowance")
        return errors
    cores=ram=disk=0
    seen=set()
    for i,node in enumerate(nodes):
        prefix=f"node[{i}]"
        if not isinstance(node,dict):
            errors.append(f"{prefix} must be object")
            continue
        if set(node)!=ALLOWED_NODE:
            errors.append(f"{prefix} missing/extra fields")
        for key in node:
            if SECRET.search(key) and key!="creates_production_consensus_keys":
                errors.append(f"{prefix} sensitive field forbidden")
        for k,v in {
          "shape":"VM.Standard.A1.Flex","architecture":"arm64",
          "operating_system":"Ubuntu arm64 Always Free Eligible",
          "host_type":"nonproduction-single-vm",
          "public_rpc_exposed":False,
          "public_ssh_exposed":False,
          "fee_denom":"atest",
          "creates_production_consensus_keys":False,
        }.items():
            if type(node.get(k)) is not type(v) or node.get(k)!=v:
                errors.append(f"{prefix}: {k} must be {v!r}")
        name=node.get("id")
        if not isinstance(name,str) or not ALLOWED_ID.fullmatch(name) or name in seen:
            errors.append(f"{prefix}: invalid/duplicate developer ID")
        seen.add(name)
        for k,minval,maxval in (("ocpus",1,2),("memory_gb",1,12),("boot_volume_gb",50,200)):
            value=node.get(k)
            if type(value) is not int or not minval<=value<=maxval:
                errors.append(f"{prefix}: {k} must be integer {minval}..{maxval}")
            else:
                if k=="ocpus":cores+=value
                elif k=="memory_gb":ram+=value
                else:disk+=value
    if cores>2: errors.append("Always Free A1 total exceeds 2 OCPUs (2026 limit)")
    if ram>12: errors.append("Always Free A1 total exceeds 12GB RAM (2026 limit)")
    if disk>200: errors.append("Always Free total block volume exceeds 200GB")
    return errors

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("candidate",type=Path)
    args=p.parse_args()
    try:
        data=json.loads(args.candidate.read_text(),object_pairs_hook=unique_keys)
    except (OSError,ValueError) as exc:
        print("REJECTED pilot document:",exc)
        return 2
    errors=assess(data)
    for e in errors:print("REJECTED:",e)
    if errors:return 2
    print("PASS: non-financial free-tier resource candidate within documented June 2026 Oracle quotas.")
    print("NO CLOUD REQUESTS SENT, NO SPENDING AUTHORIZED, NO FINANCIAL PRVI CHAIN.")
    print("REAL COST AND RESOURCE ELIGIBILITY MUST BE VERIFIED IN THE OWNER'S OCI CONSOLE.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
