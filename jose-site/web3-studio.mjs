import {networks,buildSource,validateCreationBytecode,networkById,chainManifest,appendRecord,verifyRecords} from './web3-core.mjs';
const el=(id)=>document.getElementById(id);
let generated=null,manifest=null,walletAccount=null,ledger=[],processing=false;
const LEDGER_KEY='jose-web3-ledger-v1';
function status(id,message,error=false){const e=el(id);e.textContent=message;e.classList.toggle('error',error);e.classList.toggle('success',!error&&Boolean(message));}
function kind(){return el('type').value;}
function showKind(){
 const k=kind(),isLedger=k==='ledger',isNetwork=k==='network',isTemplate=!isLedger&&!isNetwork;
 el('contractFields').hidden=!isTemplate&&!isNetwork;
 el('chainFields').hidden=!isNetwork;
 el('symbolField').hidden=!['token','nft'].includes(k);
 el('supplyField').hidden=k!=='token';
 el('sourcePanel').hidden=!isTemplate;
 el('ledgerPanel').hidden=!isLedger;
 el('networkPanel').hidden=!isNetwork;
 el('buildStatus').textContent='';
 if(!isTemplate)generated=null;
 if(isLedger)void refreshLedger();
 if(isTemplate)try{generate();}catch(e){status('buildStatus',e.message,true);}
}
function generate(){
 const k=kind();
 if(k==='ledger'){
   status('buildStatus','Local ledger ready. Append your first record and verify integrity.');
   return;
 }
 if(k==='network'){
   manifest=chainManifest({name:el('projectName').value,chainId:el('devnetId').value,validators:el('validators').value});
   el('manifest').textContent=JSON.stringify(manifest,null,2);
   status('buildStatus','Devnet blueprint created, not deployed. Export it to plan validator infrastructure.');
   return;
 }
 generated=buildSource(k,{name:el('projectName').value,symbol:el('symbol').value,supply:el('supply').value});
 el('source').value=generated.source;
 status('buildStatus',generated.label+' source generated. Review, download and compile before deployment.');
}
function download(data,filename,type){
 const url=URL.createObjectURL(new Blob([data],{type}));
 const a=document.createElement('a');a.href=url;a.download=filename;
 document.body.append(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),2000);
}
async function saveSource(){
 if(!generated)generate();
 if(generated)download(generated.source,generated.file,'text/plain;charset=utf-8');
}
async function copySource(){
 if(!generated)generate();
 if(!generated)return;
 await navigator.clipboard.writeText(generated.source);
 status('buildStatus','Solidity source copied to clipboard.');
}
async function readLedger(){
 try{
  const raw=localStorage.getItem(LEDGER_KEY);
  if(!raw)return [];
  const p=JSON.parse(raw);
  if(!Array.isArray(p))throw Error('Unexpected ledger format.');
  return p;
 }catch(e){throw Error('Saved ledger could not be read; export or back it up manually: '+e.message);}
}
async function refreshLedger(){
 try{ledger=await readLedger();}catch(e){status('ledgerStatus',e.message,true);return;}
 const list=el('ledgerList');list.replaceChildren();
 for(const record of ledger.slice(-30)){
  const li=document.createElement('li'),label=document.createElement('span'),code=document.createElement('code');
  label.textContent=String(record.index)+' · '+String(record.createdAt)+' · '+String(record.entry);
  code.textContent=String(record.hash);
  li.append(label,code);list.append(li);
 }
 const verified=await verifyRecords(ledger);
 status('ledgerStatus',ledger.length+' locally stored record(s). Integrity check: '+(verified?'PASS':'FAIL')+
   (ledger.length?' · Latest hash: '+String(ledger.at(-1)?.hash):''),!verified);
}
async function appendLedger(){
 try{
  const current=await readLedger(),entry=el('ledgerEntry').value;
  const updated=await appendRecord(current,entry);
  localStorage.setItem(LEDGER_KEY,JSON.stringify(updated));
  el('ledgerEntry').value='';
  await refreshLedger();
 }catch(e){status('ledgerStatus',e.message,true);}
}
async function verifyLedger(){
 try{
  const rows=await readLedger();
  const ok=await verifyRecords(rows);
  status('ledgerStatus',ok?'PASS: '+rows.length+' record(s) form a valid local hash chain. This is not blockchain consensus.':'FAIL: Ledger record(s) have been altered or cannot be verified.',!ok);
 }catch(e){status('ledgerStatus',e.message,true);}
}
async function exportLedger(){
 try{
  const rows=await readLedger();
  download(JSON.stringify({format:'hey-jose-hash-chain-v1',type:'local-browser-ledger',records:rows},null,2),'jose-ledger.json','application/json');
  status('ledgerStatus','Export created. Back up this file securely; local browser storage can be cleared.');
 }catch(e){status('ledgerStatus',e.message,true);}
}
function provider(){if(!window.ethereum?.request)throw new Error('No EIP-1193 browser wallet found. Install a trusted wallet such as MetaMask. Never share your seed phrase.');return window.ethereum;}
async function connectWallet(){
 try{
  const p=provider();
  const accounts=await p.request({method:'eth_requestAccounts'});
  if(!Array.isArray(accounts)||!/^0x[a-fA-F0-9]{40}$/.test(accounts[0]||''))throw new Error('Wallet did not return a valid public account.');
  walletAccount=accounts[0];
  const chain=await p.request({method:'eth_chainId'});
  status('walletStatus',walletAccount+' · Wallet chain ID '+BigInt(chain).toString(10));
 }catch(e){status('walletStatus',e.message,true);}
}
async function validateDeploy(){
 const chain=networkById(el('network').value);
 const bytecode=validateCreationBytecode(el('bytecode').value);
 if(!el('reviewed').checked)throw new Error('Review and acknowledge the contract, chain and gas conditions first.');
 if(!chain.testnet&&el('mainnetText').value!=='DEPLOY')throw new Error('Type DEPLOY to authorize a mainnet deployment.');
 const p=provider();
 const accounts=await p.request({method:'eth_accounts'});
 if(!accounts?.length)throw new Error('Connect a wallet first.');
 walletAccount=accounts[0];
 if(!/^0x[a-fA-F0-9]{40}$/.test(walletAccount))throw new Error('Invalid wallet account.');
 const actual=BigInt(await p.request({method:'eth_chainId'}));
 if(actual!==BigInt(chain.id))throw new Error('Wrong wallet network. Switch your wallet to '+chain.name+' and retry. No transaction was sent.');
 return {p,chain,bytecode,tx:{from:walletAccount,data:bytecode}};
}
async function estimate(){
 if(processing)return;
 processing=true;
 try{
  status('deployStatus','Checking network and estimating deployment gas...');
  const {p,chain,tx}=await validateDeploy();
  const gas=await p.request({method:'eth_estimateGas',params:[tx]});
  status('deployStatus','Gas estimate: '+BigInt(gas).toString()+' units on '+chain.name+'. Actual gas price and total fees depend on wallet/network. No transaction sent.');
 }catch(e){status('deployStatus',e.message,true);}
 finally{processing=false;}
}
const sleep=(ms)=>new Promise(resolve=>setTimeout(resolve,ms));
async function deploy(){
 if(processing)return;
 processing=true;el('deploy').disabled=true;
 try{
  status('deployStatus','Preparing wallet transaction...');
  const {p,chain,tx}=await validateDeploy();
  const estimate=await p.request({method:'eth_estimateGas',params:[tx]});
  const warning='Deploy a contract on '+chain.name+' using '+walletAccount+'?\n\nEstimated gas: '+BigInt(estimate).toString()+
   ' units (total fee depends on gas price).\nContract source/bytecode are NOT independently audited.\nThis action is irreversible. The wallet will request your signature.';
  if(!window.confirm(warning)){status('deployStatus','Deployment cancelled. No transaction was sent.');return;}
  status('deployStatus','Waiting for your wallet approval. Review the transaction in your wallet.');
  const txHash=await p.request({method:'eth_sendTransaction',params:[tx]});
  if(!/^0x[0-9a-fA-F]{64}$/.test(txHash))throw new Error('Wallet did not return a valid transaction hash.');
  const link=el('txLink');link.replaceChildren();
  const a=document.createElement('a');a.href=chain.explorer+'/tx/'+txHash;a.textContent='View deployment transaction on explorer';a.target='_blank';a.rel='noopener noreferrer';link.append(a);
  status('deployStatus','Submitted transaction '+txHash+'. Waiting for a block confirmation...');
  for(let i=0;i<24;i++){
    const receipt=await p.request({method:'eth_getTransactionReceipt',params:[txHash]});
    if(receipt){
      if(BigInt(receipt.status??'0x0')!==1n)throw new Error('The transaction was mined but reverted. Inspect the transaction explorer.');
      if(!/^0x[a-fA-F0-9]{40}$/.test(receipt.contractAddress||''))throw new Error('Transaction succeeded but no contract address was returned. Inspect the receipt.');
      status('deployStatus','DEPLOYED on '+chain.name+'\nContract: '+receipt.contractAddress+'\nTransaction: '+txHash+
       '\nSave the address, source code and compilation version for verification.');
      return;
    }
    await sleep(3000);
  }
  status('deployStatus','Transaction submitted but still pending. Use the explorer link to track it; do not submit duplicates without checking.');
 }catch(e){status('deployStatus',e.message,true);}
 finally{processing=false;el('deploy').disabled=false;}
}
function askJose(){
 try{
  if(kind()==='network')generate();
  else if(kind()!=='ledger')generate();
  const details=kind()==='network'?JSON.stringify(manifest,null,2):kind()==='ledger'?'Help me design an auditable ledger and secure root anchoring.':generated?.source||'';
  const msg=('Act as a Web3 engineering assistant. Review this '+kind()+' project; identify risks, requirements, and next steps. Produce a clear improvement plan and sample source if helpful. Never claim it was deployed. '+details).slice(0,11000);
  const panel=el('aiPanel'),frame=el('aiFrame');panel.hidden=false;
  frame.onload=()=>frame.contentWindow?.postMessage({type:'jose-initial-message',mode:'web3',message:msg},'https://jose-backend-075d.onrender.com');
  frame.src='https://jose-backend-075d.onrender.com/chat.html';
  panel.scrollIntoView({behavior:'smooth'});
 }catch(e){status('buildStatus',e.message,true);}
}
el('type').addEventListener('change',showKind);
el('generate').addEventListener('click',()=>{try{generate();}catch(e){status('buildStatus',e.message,true);}});
el('askJose').addEventListener('click',askJose);
el('downloadSource').addEventListener('click',()=>void saveSource().catch(e=>status('buildStatus',e.message,true)));
el('copySource').addEventListener('click',()=>void copySource().catch(e=>status('buildStatus',e.message,true)));
el('downloadManifest').addEventListener('click',()=>{try{generate();download(JSON.stringify(manifest,null,2),'jose-blockchain-devnet-blueprint.json','application/json');}catch(e){status('buildStatus',e.message,true);}});
el('appendLedger').addEventListener('click',()=>void appendLedger());
el('verifyLedger').addEventListener('click',()=>void verifyLedger());
el('exportLedger').addEventListener('click',()=>void exportLedger());
el('walletConnect').addEventListener('click',()=>void connectWallet());
el('estimate').addEventListener('click',()=>void estimate());
el('deploy').addEventListener('click',()=>void deploy());
el('network').addEventListener('change',()=>{const n=networkById(el('network').value);el('mainnetAck').hidden=n.testnet;el('mainnetText').value='';el('reviewed').checked=false;});
if(window.ethereum?.on){
 window.ethereum.on('accountsChanged',(accounts)=>{walletAccount=accounts?.[0]||null;status('walletStatus',walletAccount?'Wallet account changed: '+walletAccount:'Wallet disconnected.');el('reviewed').checked=false;});
 window.ethereum.on('chainChanged',()=>{status('walletStatus','Wallet chain changed; reconnect and confirm before deploying.');el('reviewed').checked=false;});
}
showKind();
