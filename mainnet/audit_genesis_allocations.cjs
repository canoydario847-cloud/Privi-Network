'use strict';
// Offline manifest-based bank allocation audit. Does not validate vesting schedules or staking state.
const fs=require('node:fs');
const integer=/^(0|[1-9][0-9]*)$/;
function auditAllocations(genesis,manifest) {
 const errors=[];
 if(!manifest||!Array.isArray(manifest.allocations)||manifest.allocations.length===0)return ['missing allocation manifest'];
 if(manifest.requireExactAccounts!==true)return ['requireExactAccounts must be true for production allocation audit'];
 if(typeof manifest.denom!=='string'||!/^a[a-z][a-z0-9]{2,63}$/.test(manifest.denom))return ['invalid manifest denom'];
 const balances=genesis?.app_state?.bank?.balances;
 if(!Array.isArray(balances))return ['missing bank balances'];
 const actual=new Map();
 for(const entry of balances){
  if(!entry||typeof entry.address!=='string'||!entry.address||!Array.isArray(entry.coins)){errors.push('invalid bank entry');continue;}
  for(const coin of entry.coins){
   if(coin?.denom!==manifest.denom)continue;
   if(typeof coin.amount!=='string'||!integer.test(coin.amount)){errors.push('invalid bank amount');continue;}
   if(actual.has(entry.address)){errors.push('duplicate bank allocation address '+entry.address);continue;}
   actual.set(entry.address,BigInt(coin.amount));
  }
 }
 const expected=new Map();
 for(const item of manifest.allocations){
  if(!item||typeof item.address!=='string'||!item.address||typeof item.amount!=='string'||!integer.test(item.amount)){errors.push('invalid manifest allocation');continue;}
  if(expected.has(item.address)){errors.push('duplicate manifest address '+item.address);continue;}
  expected.set(item.address,BigInt(item.amount));
 }
 for(const [address,amount] of expected)if(!actual.has(address)||actual.get(address)!==amount)errors.push('allocation mismatch '+address);
 for(const address of actual.keys())if(!expected.has(address))errors.push('unexpected allocation '+address);
 return errors;
}
if(require.main===module){
 const [genesisFile,manifestFile]=process.argv.slice(2);
 if(!genesisFile||!manifestFile){console.error('Usage: node audit_genesis_allocations.cjs genesis.json approved-allocations.json');process.exitCode=2;}
 else try{
  const errors=auditAllocations(JSON.parse(fs.readFileSync(genesisFile,'utf8')),JSON.parse(fs.readFileSync(manifestFile,'utf8')));
  if(errors.length){console.error('NO-GO: '+errors.join('; '));process.exitCode=1;}
  else console.log('Listed bank allocations match manifest. Manifest approval, vesting, staking and launch readiness NOT verified.');
 }catch(e){console.error('NO-GO: '+e.message);process.exitCode=1;}
}
module.exports={auditAllocations};
