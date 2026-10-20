#!/usr/bin/env python3
"""Read-only proof of four CometBFT voting validators (>2/3 signatures)."""
import argparse
import json
from urllib.parse import urlencode
from urllib.request import urlopen

def get(base,route):
    with urlopen(base.rstrip('/')+route,timeout=12) as res:
        if res.status!=200:raise RuntimeError('HTTP '+str(res.status))
        data=json.load(res)
    if data.get('error'):raise RuntimeError(str(data['error']))
    return data['result']

def validator_set(url,height):
    found={}
    page=1
    while True:
        response=get(url,'/validators?'+urlencode({'height':str(height),'page':page,'per_page':100}))
        for v in response['validators']:
            key=v['address'].upper()
            if key in found:raise ValueError('Duplicate validator')
            found[key]=int(v['voting_power'])
        if len(found)>=int(response['total']):return found
        page+=1
        if page>1000:raise ValueError('Validator pagination excessive')

def signed_power_from_commit(commit, height, block_hash, voters):
    """Count unique commit votes on one endpoint; never assert native PoP finality."""
    if not isinstance(commit, dict) or str(commit.get('height'))!=str(height):
        raise ValueError('Commit height mismatch')
    block_id=commit.get('block_id')
    if not isinstance(block_id,dict) or block_id.get('hash')!=block_hash:
        raise ValueError('Commit hash mismatch')
    signatures=commit.get('signatures')
    if not isinstance(signatures,list):
        raise ValueError('Missing commit signatures')
    seen=set()
    signed_power=0
    for sig in signatures:
        if not isinstance(sig,dict):
            raise ValueError('Malformed commit vote')
        key=str(sig.get('validator_address','')).upper()
        if key:
            if key in seen:
                raise ValueError('Duplicate validator vote in commit')
            seen.add(key)
        if str(sig.get('block_id_flag')) not in ('2','BLOCK_ID_FLAG_COMMIT'):
            continue
        if key not in voters or not isinstance(sig.get('signature'),str) or not sig['signature']:
            raise ValueError('Unknown or unsigned commit validator')
        signed_power+=voters[key]
    total=sum(voters.values())
    if 3*signed_power<=2*total:
        raise ValueError('Insufficient signatures')
    return signed_power

def audit(urls,expected='local-4221'):
    if len(urls)<4:raise ValueError('Provide >=4 CometBFT endpoints')
    statuses=[get(u,'/status') for u in urls]
    ids=[s['node_info']['id'] for s in statuses]
    chains=[s['node_info']['network'] for s in statuses]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate peer IDs')
    if len(set(chains))!=1 or (expected and chains[0]!=expected):raise ValueError('Wrong Cosmos chain ID')
    heights=[int(s['sync_info']['latest_block_height']) for s in statuses]
    if min(heights)<2 or max(heights)-min(heights)>10 or any(s['sync_info']['catching_up'] for s in statuses):
        raise ValueError('Nodes not synchronized')
    height=min(heights)-1
    hashes=[get(u,'/block?height='+str(height))['block_id']['hash'] for u in urls]
    if len(set(hashes))!=1:raise ValueError('Block hashes disagree')
    sets=[validator_set(u,height) for u in urls]
    if any(v!=sets[0] for v in sets[1:]):raise ValueError('Validator sets disagree')
    voters={k:v for k,v in sets[0].items() if v>0}
    if len(voters)<4:raise ValueError('Fewer than four voting validators')
    # Every RPC must independently report a matching height/hash and a
    # >2/3 unique-voting-power commit. One healthy endpoint is not evidence
    # that every node agrees. RPC-provided signatures are not independently
    # cryptographically verified here; this is NOT native Point of Position.
    powers=[]
    for url in urls:
        response=get(url,'/commit?height='+str(height))
        header=response.get('signed_header') if isinstance(response,dict) else None
        if not isinstance(header,dict):
            raise ValueError('Missing signed commit header')
        powers.append(signed_power_from_commit(header.get('commit'),height,hashes[0],voters))
    total=sum(voters.values())
    return {'cosmosChainId':chains[0],'blockHeight':height,'blockHash':hashes[0],
            'nodes':len(urls),'votingValidators':len(voters),
            'signedVotingPower':min(powers),'totalVotingPower':total,
            'commitEndpointsChecked':len(powers),
            'consensusType':'UPSTREAM_COMETBFT_NOT_NATIVE_POP',
            'warning':'RPC commit evidence is not cryptographically verified here; four local validator processes are NOT four independent operators or native PoP finality'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rpc',action='append',required=True)
    p.add_argument('--chain-id',default='local-4221')
    args=p.parse_args()
    try:print(json.dumps({'ok':True,**audit(args.rpc,args.chain_id)},indent=2))
    except Exception as e:
        print(json.dumps({'ok':False,'error':str(e)}))
        raise SystemExit(1) from e
if __name__=='__main__':main()
