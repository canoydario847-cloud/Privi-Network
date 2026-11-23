import test from 'node:test';
import assert from 'node:assert/strict';
import {createDevnetClient,verifyDevnetIdentity,devnetQuestion,DEVNET_EVM_ID} from '../src/privi-devnet.js';

const NOW=1784900000000;
const HEIGHT=1042;
function health(){
  return {ok:true,network:'Privi Devnet',cosmos_chain_id:'privi-devnet-1',
    evm_chain_id:DEVNET_EVM_ID,latest_block:HEIGHT,
    latest_block_time:Math.floor(NOW/1000)-5,seconds_since_block:5};
}
function fakeFetch({chain='0xbc9f2',block='0x412',healthy=true}={}){
  const requests=[];
  const fetchImpl=async(url,options={})=>{
    requests.push({url,method:options.method||'GET'});
    if(url.endsWith('/health'))return {ok:healthy,status:healthy?200:503,json:async()=>health()};
    const body=JSON.parse(options.body);
    const result=body.method==='eth_chainId'?chain:body.method==='eth_blockNumber'?block:
      body.method==='eth_getBalance'?'0xde0b6b3a7640000':'0x0';
    return {ok:true,status:200,json:async()=>({jsonrpc:'2.0',id:1,result})};
  };
  return {fetchImpl,requests};
}
test('checks both REST health and RPC identity, never just HTTP 200',async()=>{
 const f=fakeFetch({chain:'0xbc9f2'});
 const client=createDevnetClient({fetchImpl:f.fetchImpl,now:()=>NOW});
 const status=await client.check();
 assert.equal(status.connected,DEVNET_EVM_ID===Number(BigInt('0xbc9f2')));
 // The fake first mismatches intentionally, so fail closed.
 assert.equal(status.connected,false);
 assert.equal(status.writesEnabled,false);
 assert.equal(status.financialMainnet,false);
 assert.equal(f.requests.length,3);
});
test('verifies healthy height on canonical 772626 devnet',async()=>{
 const f=fakeFetch({chain:'0xbca12'});
 // Always derive the authoritative hex ID, not the upstream example.
 const target='0x'+DEVNET_EVM_ID.toString(16);
 const full=fakeFetch({chain:target});
 const client=createDevnetClient({fetchImpl:full.fetchImpl,now:()=>NOW});
 const report=await client.check();
 assert.equal(report.connected,true);
 assert.equal(report.observedEvmChainId,772626);
 assert.equal(report.latestBlock,HEIGHT);
 assert.equal(report.currency,'TEST (valueless)');
 await client.check();
 assert.equal(full.requests.length,3,'cached probes');
});
test('refuses wrong chain IDs and stale heads',()=>{
 const valid=verifyDevnetIdentity(health(),'0x'+DEVNET_EVM_ID.toString(16),'0x412',NOW/1000);
 assert.equal(valid.connected,true);
 assert.equal(verifyDevnetIdentity(health(),'0x40000','0x412',NOW/1000).connected,false);
 const old=health();old.latest_block_time-=3600;
 assert.equal(verifyDevnetIdentity(old,'0x'+DEVNET_EVM_ID.toString(16),'0x412',NOW/1000).connected,false);
});
test('public balance lookup needs an address and verified chain',async()=>{
 const f=fakeFetch({chain:'0x'+DEVNET_EVM_ID.toString(16)});
 const client=createDevnetClient({fetchImpl:f.fetchImpl,now:()=>NOW});
 await assert.rejects(()=>client.balance('not-an-address'),/public EVM/);
 const row=await client.balance('0x0000000000000000000000000000000000000001');
 assert.equal(row.balanceWei,'1000000000000000000');
 assert.equal(row.asset,'TEST (valueless)');
});
test('queries read only endpoints and answers status questions',()=>{
 assert.equal(devnetQuestion('What is the Privi devnet status?'),true);
 assert.equal(devnetQuestion('check the devnet block height'),true);
 assert.equal(devnetQuestion('Write a song about Detroit'),false);
});
