#!/usr/bin/env python3
"""Read-only real Ethereum JSON-RPC probe; never fakes MetaMask readiness."""
import argparse
import json
import urllib.request

class RPC:
    def __init__(self,url):self.url,self.counter=url,0
    def call(self,method,params=None):
        self.counter+=1
        body=json.dumps({'jsonrpc':'2.0','id':self.counter,'method':method,'params':params or []}).encode()
        request=urllib.request.Request(self.url,data=body,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=12) as res:
            if res.status!=200:raise RuntimeError('HTTP '+str(res.status))
            data=json.load(res)
        if data.get('error') is not None:raise RuntimeError(str(data['error']))
        if 'result' not in data:raise RuntimeError('Missing JSON-RPC result')
        return data['result']

def check(rpc,expected=None,address=None):
    chain=int(rpc.call('eth_chainId'),16)
    if chain<=0 or chain in (1,56,97):raise ValueError('Unsafe/production EVM chain ID')
    if expected is not None and chain!=expected:raise ValueError(f'EVM chain ID mismatch: expected {expected}, observed {chain}')
    height=int(rpc.call('eth_blockNumber'),16)
    if height<1:raise ValueError('No blocks available yet')
    block=rpc.call('eth_getBlockByNumber',[hex(height),False])
    if not block or not block.get('hash'):raise ValueError('Block unavailable')
    result={'chainId':chain,'blockHeight':height,'blockHash':block['hash']}
    if address:
        if len(address)!=42 or not address.startswith('0x') or not all(c in '0123456789abcdefABCDEF' for c in address[2:]):
            raise ValueError('Invalid EVM 0x address')
        result['address']=address
        result['balanceWei']=str(int(rpc.call('eth_getBalance',[address,'latest']),16))
        result['pendingNonce']=int(rpc.call('eth_getTransactionCount',[address,'pending']),16)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rpc',default='http://127.0.0.1:8545')
    p.add_argument('--expect-chain',type=int)
    p.add_argument('--address')
    args=p.parse_args()
    try:print(json.dumps({'ok':True,**check(RPC(args.rpc),args.expect_chain,args.address)},indent=2))
    except Exception as e:
        print(json.dumps({'ok':False,'error':str(e)}))
        raise SystemExit(1) from e
if __name__=='__main__':main()
