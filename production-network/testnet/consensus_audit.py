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
    # Four RPC peers do not prove four validator signing identities: sentry
    # nodes can serve the same validator set without signing any blocks.
    local_signers=[]
    for status in statuses:
        info=status.get('validator_info') or {}
        address=str(info.get('address') or '').upper()
        try:
            power=int(info.get('voting_power', 0))
        except (TypeError, ValueError) as exc:
            raise ValueError('Invalid local validator voting power') from exc
        if not address or address not in voters or power<=0:
            raise ValueError('RPC endpoint is not a voting validator signer')
        if power!=voters[address]:
            raise ValueError('Local validator voting power disagrees with validator set')
        local_signers.append(address)
    if len(set(local_signers))!=len(local_signers):
        raise ValueError('Duplicate validator signing identities across RPC endpoints')
    commit=get(urls[0],'/commit?height='+str(height))['signed_header']['commit']
    if commit['block_id']['hash']!=hashes[0]:raise ValueError('Commit hash mismatch')
    signed={s.get('validator_address','').upper() for s in commit['signatures']
            if str(s.get('block_id_flag')) in ('2','BLOCK_ID_FLAG_COMMIT') and s.get('signature')}
    total=sum(voters.values())
    signed_power=sum(power for key,power in voters.items() if key in signed)
    if 3*signed_power<=2*total:raise ValueError('Insufficient signatures')
    return {'cosmosChainId':chains[0],'blockHeight':height,'blockHash':hashes[0],
            'nodes':len(urls),'votingValidators':len(voters),
            'signedVotingPower':signed_power,'totalVotingPower':total,
            'warning':'Four local validator processes are NOT four independent operators'}

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
