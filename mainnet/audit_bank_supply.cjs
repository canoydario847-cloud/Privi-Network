'use strict';
// Offline bank supply reconciliation only. Does not establish staking/vesting correctness.
const fs=require('node:fs');
const integer=/^(0|[1-9][0-9]*)$/;
const UINT256_MAX=(1n<<256n)-1n;
// Validate length before BigInt parsing; Cosmos SDK coin amounts must fit uint256.
const validAmount=value=>typeof value==='string' && value.length<=78 && integer.test(value) && BigInt(value)<=UINT256_MAX;
// Reject whitespace/control characters in identifiers before accounting.
const validIdentifier=value=>typeof value==='string' && value.length>0 && !/[\s\x00-\x1f\x7f]/u.test(value);
function auditBankSupply(genesis){
 const errors=[];
 const bank=genesis?.app_state?.bank;
 if(!Array.isArray(bank?.balances)||!Array.isArray(bank?.supply))return ['missing bank balances or supply'];
 const totals=new Map(),supplies=new Map(),addresses=new Set();
 for(const entry of bank.balances){
  if(!entry||!validIdentifier(entry.address)||addresses.has(entry.address)||!Array.isArray(entry.coins)){
   errors.push('invalid or duplicate bank balance address');continue;
  }
  addresses.add(entry.address);
  const seen=new Set();
  for(const coin of entry.coins){
   if(!coin||!validIdentifier(coin.denom)||!validAmount(coin.amount)){
    errors.push('invalid bank balance coin');continue;
   }
   if(seen.has(coin.denom)){errors.push('duplicate balance denom '+coin.denom);continue;}
   seen.add(coin.denom);
   totals.set(coin.denom,(totals.get(coin.denom)||0n)+BigInt(coin.amount));
  }
 }
 for(const coin of bank.supply){
  if(!coin||!validIdentifier(coin.denom)||!validAmount(coin.amount)){
   errors.push('invalid supply coin');continue;
  }
  if(supplies.has(coin.denom)){errors.push('duplicate supply denom '+coin.denom);continue;}
  supplies.set(coin.denom,BigInt(coin.amount));
 }
 for(const [denom,total] of totals){
  if(total>UINT256_MAX)errors.push('bank balance sum exceeds uint256 '+denom);
  if(!supplies.has(denom)||supplies.get(denom)!==total)errors.push('supply mismatch '+denom);
 }
 for(const [denom,amount] of supplies)if(!totals.has(denom)&&amount!==0n)errors.push('unbacked supply '+denom);
 return errors;
}
if(require.main===module){
 const path=process.argv[2];
 if(!path){console.error('Usage: node audit_bank_supply.cjs genesis.json');process.exitCode=2;}
 else try{
  const errors=auditBankSupply(JSON.parse(fs.readFileSync(path,'utf8')));
  if(errors.length){console.error('NO-GO: '+errors.join('; '));process.exitCode=1;}
  else console.log('Bank supply reconciles to bank balances only. Staking, vesting, manifest approval and launch readiness NOT verified.');
 }catch(e){console.error('NO-GO: '+e.message);process.exitCode=1;}
}
module.exports={auditBankSupply};
