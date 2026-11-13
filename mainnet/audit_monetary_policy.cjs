'use strict';
// Offline, fail-closed policy check. Policy must be independently approved.
const UINT256_MAX=(1n<<256n)-1n;
const amount=x=>typeof x==='string'&&/^(0|[1-9][0-9]*)$/.test(x)&&x.length<=78&&BigInt(x)<=UINT256_MAX;
const identifier=x=>typeof x==='string'&&x.length>0&&!/[\s\x00-\x1f\x7f]/u.test(x);
function auditMonetaryPolicy(genesis,policy){
 const errors=[];
 if(!policy||policy.approved!==true||!identifier(policy.denom)||!amount(policy.maxSupply))return ['missing or unapproved monetary policy'];
 const bank=genesis?.app_state?.bank;
 if(!Array.isArray(bank?.balances)||!Array.isArray(bank?.supply))return ['missing bank balances or supply'];
 const allowed=new Set([policy.denom]);
 if(policy.allowedDenoms!==undefined){
  if(!Array.isArray(policy.allowedDenoms)||policy.allowedDenoms.some(d=>!identifier(d)))return ['invalid allowed denominations'];
  for(const d of policy.allowedDenoms)allowed.add(d);
 }
 const supply=new Map();
 for(const coin of bank.supply){
  if(!coin||!identifier(coin.denom)||!amount(coin.amount)){errors.push('invalid supply entry');continue;}
  if(!allowed.has(coin.denom))errors.push('unauthorized supply denomination '+coin.denom);
  if(supply.has(coin.denom))errors.push('duplicate supply denomination '+coin.denom);
  supply.set(coin.denom,BigInt(coin.amount));
 }
 for(const entry of bank.balances){
  if(!entry||!Array.isArray(entry.coins)){errors.push('invalid bank balance entry');continue;}
  for(const coin of entry.coins){
   if(!coin||!identifier(coin.denom)||!amount(coin.amount)){errors.push('invalid balance coin');continue;}
   if(!allowed.has(coin.denom))errors.push('unauthorized balance denomination '+coin.denom);
  }
 }
 if(!supply.has(policy.denom))errors.push('missing native supply '+policy.denom);
 else if(supply.get(policy.denom)>BigInt(policy.maxSupply))errors.push('native supply exceeds policy cap');
 return errors;
}
module.exports={auditMonetaryPolicy};
