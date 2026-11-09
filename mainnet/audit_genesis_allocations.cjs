'use strict';
// Offline allocation reconciliation only. Does NOT verify on-chain vesting enforcement.
const {auditBankSupply}=require('./audit_bank_supply.cjs');
const amount=v=>typeof v==='string'&&/^(0|[1-9][0-9]*)$/.test(v)&&v.length<=78&&BigInt(v)<=(1n<<256n)-1n;
function auditGenesisAllocations(genesis,allocationManifest){
 const errors=auditBankSupply(genesis);
 if(!allocationManifest||typeof allocationManifest!=='object'||Array.isArray(allocationManifest)||!Array.isArray(allocationManifest.allocations))
  return [...errors,'missing allocation manifest'];
 const balances=new Map();
 for(const entry of genesis?.app_state?.bank?.balances||[]){
  if(entry&&typeof entry.address==='string'&&!balances.has(entry.address))balances.set(entry.address,entry.coins);
 }
 const seen=new Set();
 for(const entry of allocationManifest.allocations){
  if(!entry||typeof entry.address!=='string'||!entry.address||typeof entry.denom!=='string'||!entry.denom||!amount(entry.amount)){
   errors.push('invalid allocation');continue;
  }
  const key=JSON.stringify([entry.address,entry.denom]);
  if(seen.has(key)){errors.push('duplicate allocation');continue;}
  seen.add(key);
  const coins=balances.get(entry.address);
  if(!Array.isArray(coins)){errors.push('allocation address missing from bank');continue;}
  const coin=coins.find(c=>c?.denom===entry.denom);
  if(!coin||coin.amount!==entry.amount)errors.push('allocation differs from bank balance');
 }
 if(allocationManifest.allocations.length===0)errors.push('empty allocation manifest');
 return errors;
}
module.exports={auditGenesisAllocations};
