'use strict';
// Offline allocation reconciliation only. Does NOT verify on-chain vesting enforcement.
const {auditBankSupply}=require('./audit_bank_supply.cjs');
const identifier=v=>typeof v==='string'&&v.length>0&&!/[\s\x00-\x1f\x7f]/u.test(v);
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
  if(!entry||!identifier(entry.address)||!identifier(entry.denom)||!amount(entry.amount)){
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
 // Fail closed if a bank balance coin is omitted from the approved allocation list.
 // This is an exact address+denom comparison, not an aggregate-supply comparison.
 for(const [address,coins] of balances){
  if(!Array.isArray(coins))continue; // auditBankSupply already reports invalid shapes.
  for(const coin of coins){
   if(coin&&typeof coin.denom==='string'&&!seen.has(JSON.stringify([address,coin.denom])))
    errors.push('bank balance missing from allocation manifest');
  }
 }
 if(allocationManifest.allocations.length===0)errors.push('empty allocation manifest');
 return errors;
}
module.exports={auditGenesisAllocations};
