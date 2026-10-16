#!/usr/bin/env python3
"""Public-chain-data export only. DOES NOT back up validator private keys."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_URL = 'https://privi-network-production.up.railway.app'

def hash_object(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def verify_blocks(blocks):
    if not blocks:
        raise ValueError('Empty chain')
    validator = None
    for height, b in enumerate(blocks):
        if b['index'] != height or b['chainId'] != 'privi-dev-1':
            raise ValueError('Unexpected block identity')
        core={k:b[k] for k in ('index','chainId','timestamp','previousHash','merkleRoot','validator','transactions')}
        if hash_object(core) != b['hash']:
            raise ValueError('Invalid block hash at height %d' % height)
        if not height:
            if b['validator'] != 'GENESIS' or b['previousHash'] != '0'*64:
                raise ValueError('Invalid genesis')
        else:
            if b['previousHash'] != blocks[height-1]['hash']:
                raise ValueError('Broken chain links')
            if validator is None:
                validator=b['validator']
            if b['validator'] != validator:
                raise ValueError('Validator changed')
    return {'height':len(blocks)-1,'headHash':blocks[-1]['hash'],'validatorAddress':validator}

def get(base,route):
    req=Request(base.rstrip('/')+route,headers={'User-Agent':'Privi-Public-Snapshot/1'})
    with urlopen(req, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError('HTTP %d' % response.status)
        data=response.read(4*1024*1024+1)
        if len(data)>4*1024*1024:
            raise ValueError('Response too large')
    return json.loads(data)

def snapshot(url,max_height):
    parsed=urlparse(url)
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')):
        raise ValueError('Remote URLs must use HTTPS')
    status=get(url,'/api/status')
    if status.get('chainId')!='privi-dev-1':
        raise ValueError('Wrong source chain')
    height=status.get('height')
    if type(height)!=int or not (0<=height<=max_height):
        raise ValueError('Invalid/excessive chain height')
    blocks=[get(url,'/api/block/'+str(i)) for i in range(height+1)]
    proof=verify_blocks(blocks)
    if status.get('latestHash')!=proof['headHash']:
        raise ValueError('Head moved; pause writes and retry')
    return {'type':'PUBLIC_BLOCKS_ONLY','warning':'NOT a restorable validator backup','source':url,'chainId':'privi-dev-1','proof':proof,'blocks':blocks}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',default=DEFAULT_URL)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--max-height',type=int,default=100000)
    args=p.parse_args()
    if args.max_height<0:
        p.error('Invalid maximum height')
    result=snapshot(args.url,args.max_height)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(args.out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf8') as file:
        json.dump(result,file,indent=2,ensure_ascii=False)
        file.write('\n')
    print('Saved public blocks:',result['proof']['height']+1)
    print('ALSO BACK UP validator.pem separately and privately before migration.')
if __name__=='__main__':main()
