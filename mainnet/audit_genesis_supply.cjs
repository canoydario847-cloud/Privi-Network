'use strict';
// Offline Cosmos SDK bank genesis consistency audit. Not a complete monetary audit.
const fs=require('node:fs');
function audit(genesis, expectedDenom, expectedSupply) {
 const errors=[];
 if(typeof expectedDenom!=='string'||!/^a[a-z][a-z0-9]{2,63}$/.test(expectedDenom)) return ['invalid expected base denomination'];
 if(typeof expectedSupply!=='string'||!/^(0|[1-9][0-9]*)$/.test(expectedSupply)) return ['invalid expected supply'];
 const bank=genesis?.app_state?.bank;
 if(!bank||!Array.isArray(bank.balances)||!Array.isArray(bank.supply)) return ['missing Cosmos bank balances or supply'];
 const totals=new Map(), supplied=new Map(), seenAccounts=new Set();
 function add(map,coin,where) {
  if(!coin||typeof coin.denom!=='string'||!coin.denom||typeof coin.amount!=='string'||!/^(0|[1-9][0-9]*)$/.test(coin.amount)){errors.push('invalid coin in '+where);return;}
  if(map===supplied&&map.has(coin.denom)){errors.push('duplicate supply denom '+coin.denom);return;}
  map.set(coin.denom,(map.get(coin.denom)||0n)+BigInt(coin.amount));
 }
 for(const entry of bank.balances){
  if(!entry||typeof entry.address!=='string'||!entry.address||seenAccounts.has(entry.address)||!Array.isArray(entry.coins)){errors.push('invalid or duplicate bank account');continue;}
  seenAccounts.add(entry.address);
  const seenDenoms=new Set();
  for(const coin of entry.coins){if(coin&&seenDenoms.has(coin.denom)){errors.push('duplicate balance denom');continue;}if(coin)seenDenoms.add(coin.denom);add(totals,coin,'balance');}
 }
 for(const coin of bank.supply)add(supplied,coin,'supply');
 for(const denom of new Set([...totals.keys(),...supplied.keys()]))if((totals.get(denom)||0n)!==(supplied.get(denom)||0n))errors.push('bank supply mismatch for '+denom);
 if(!supplied.has(expectedDenom))errors.push('expected PRVI denomination missing from bank supply');
 if((supplied.get(expectedDenom)||0n)!==BigInt(expectedSupply))errors.push('expected PRVI supply mismatch');
 return errors;
}
if(require.main===module){
 const [file,denom,supply]=process.argv.slice(2);
 if(!file||!denom||!supply){console.error('Usage: node audit_genesis_supply.cjs genesis.json base-denom expected-base-units');process.exitCode=2;}
 else try{const errors=audit(JSON.parse(fs.readFileSync(file,'utf8')),denom,supply);if(errors.length){console.error('NO-GO: '+errors.join('; '));process.exitCode=1;}else console.log('Bank supply consistent with provided expected amount; other modules, vesting, ownership, provenance and launch readiness NOT verified.');}
 catch(e){console.error('NO-GO: '+e.message);process.exitCode=1;}
}
module.exports={audit};
