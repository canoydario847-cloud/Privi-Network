// Read-only Privi Devnet integration for Hey Jose.
// This is an externally hosted single-validator TEST network, NOT financial PRVI mainnet.
// Chain ID 772626 is Privi Devnet; 262144 is the unrelated upstream sample.
export const DEVNET_URL='https://privi-devnet-32v2.onrender.com';
export const DEVNET_EVM_ID=772626;
export const DEVNET_COSMOS_ID='privi-devnet-1';
const MAX_AGE_MS=120_000;
const CHECK_TTL_MS=15_000;
const EVM_ADDRESS=/^0x[0-9a-fA-F]{40}$/;
const HEX=/^0x[0-9a-fA-F]+$/;
const TX_HASH=/^0x[0-9a-fA-F]{64}$/;

export function devnetQuestion(message){
  const text=String(message||'').toLowerCase();
  return /\b(?:privi[\s-]?)?devnet\b/.test(text)
    && /\b(?:status|health|online|connected|working|running|blocks?|height|network|rpc|chain[\s-]?id|alive|up|ready|check)\b/.test(text);
}

export function devnetDetailsQuestion(message){
  return /\bdevnet\b/i.test(String(message||''));
}

export function verifyDevnetIdentity(health,chainId,height,nowSeconds=Date.now()/1000){
  const id=typeof chainId==='string'&&HEX.test(chainId)?Number(BigInt(chainId)):null;
  const block=typeof height==='string'&&HEX.test(height)?Number(BigInt(height)):null;
  const age=Number(health?.seconds_since_block);
  const timestamp=Number(health?.latest_block_time);
  const safe=Number.isSafeInteger(block)&&block>=1
    &&Number.isSafeInteger(id)&&id===DEVNET_EVM_ID
    &&health?.ok===true
    &&health?.network==='Privi Devnet'
    &&health?.evm_chain_id===DEVNET_EVM_ID
    &&health?.cosmos_chain_id===DEVNET_COSMOS_ID
    &&Number.isFinite(age)&&age>=0&&age<120
    &&Number.isFinite(timestamp)&&Math.abs(nowSeconds-timestamp)<MAX_AGE_MS/1000
    &&Number.isSafeInteger(Number(health?.latest_block))
    &&Math.abs(Number(health.latest_block)-block)<=3;
  return {
    connected:Boolean(safe),network:'Privi Devnet',expectedEvmChainId:DEVNET_EVM_ID,
    observedEvmChainId:Number.isSafeInteger(id)?id:null,cosmosChainId:DEVNET_COSMOS_ID,
    latestBlock:Number.isSafeInteger(block)?block:null,
    blockAgeSeconds:Number.isFinite(age)&&age>=0?age:null,
    currency:'TEST (valueless)',
    rpcUrl:DEVNET_URL,
    service:'Hey Jose read-only devnet connection',
    writesEnabled:false,financialMainnet:false,
    reason:safe?'Verified live block, expected identity and RPC chain ID':'RPC identity, health or block freshness could not be verified'
  };
}

export function createDevnetClient({fetchImpl=globalThis.fetch,now=()=>Date.now(),timeoutMs=6000}={}){
  if(typeof fetchImpl!=='function')throw new TypeError('fetch required');
  let last=null,pending=null,checkedAtMs=-Infinity;
  async function request(url,init={}){
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),timeoutMs);
    try{
      const res=await fetchImpl(url,{...init,redirect:'error',cache:'no-store',signal:controller.signal});
      if(!res.ok)throw new Error('Devnet unavailable (HTTP '+res.status+')');
      return await res.json();
    }finally{clearTimeout(timer);}
  }
  async function rpc(method,params=[]){
    const response=await request(DEVNET_URL+'/rpc',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})
    });
    if(response?.jsonrpc!=='2.0'||response?.id!==1||response.error||typeof response?.result!=='string')
      throw new Error('Invalid devnet JSON-RPC response');
    return response.result;
  }
  async function check(force=false){
    if(!force&&last&&now()-checkedAtMs<CHECK_TTL_MS)return last;
    if(pending)return pending;
    pending=(async()=>{
      let report;
      try{
        const [health,chainId,height]=await Promise.all([
          request(DEVNET_URL+'/health',{method:'GET'}),rpc('eth_chainId'),rpc('eth_blockNumber')
        ]);
        report=verifyDevnetIdentity(health,chainId,height,now()/1000);
      }catch{
        report=verifyDevnetIdentity(null,null,null,now()/1000);
        report.reason='Devnet endpoint unavailable or failed identity checks';
      }
      last=Object.freeze({...report,checkedAt:new Date(now()).toISOString()});
      checkedAtMs=now();
      return last;
    })();
    try{return await pending;}finally{pending=null;}
  }
  async function balance(address){
    if(!EVM_ADDRESS.test(address||''))throw new Error('Provide a valid public EVM address.');
    const status=await check();
    if(!status.connected)throw new Error('Privi Devnet identity is not verified. Refusing to query another network.');
    const wei=await rpc('eth_getBalance',[address,'latest']);
    if(!HEX.test(wei))throw new Error('Invalid balance response.');
    return {
      address,network:'Privi Devnet',chainId:DEVNET_EVM_ID,
      balanceWei:BigInt(wei).toString(),
      asset:'TEST (valueless)',checkedAt:new Date(now()).toISOString()
    };
  }
  async function receipt(hash){
    if(!TX_HASH.test(hash||''))throw new Error('Provide a valid 0x-prefixed 32-byte transaction hash.');
    const status=await check();
    if(!status.connected)throw new Error('Privi Devnet identity is not verified. Refusing another network.');
    // Use read-only explorer; don't provide a transaction signer or broadcast capability.
    const data=await request(DEVNET_URL+'/api/tx/'+hash,{method:'GET'});
    if(data?.chain_id!==DEVNET_EVM_ID||data?.hash?.toLowerCase()!==hash.toLowerCase())
      throw new Error('Transaction is not verified for Privi Devnet');
    return {hash:data.hash,network:'Privi Devnet',chainId:DEVNET_EVM_ID,block:data.block??null,status:data.status??'unknown',explorerUrl:DEVNET_URL+'/tx/'+hash};
  }
  return Object.freeze({check,balance,receipt});
}
