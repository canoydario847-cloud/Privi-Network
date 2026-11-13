#!/usr/bin/env node
'use strict';
// Offline artifact integrity check. Does not attest to provenance or authorize launch.
const fs=require('node:fs');
const crypto=require('node:crypto');
const path=require('node:path');
const {check}=require('./readiness.cjs');
function verify(m,files){
 const errors=check(m);
 if(errors.length)return errors;
 for(const [field,file] of [['genesis_sha256',files.genesis],['binary_sha256',files.binary]]){
  if(typeof file!=='string'||!file.trim()){errors.push('missing artifact path for '+field);continue;}
  try{
   const stat=fs.lstatSync(file);
   if(!stat.isFile()||stat.isSymbolicLink()){errors.push('artifact is not a regular file: '+field);continue;}
   const actual=crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
   if(actual!==m[field])errors.push('digest mismatch: '+field);
   if(field==='genesis_sha256' && actual===m[field]){
    try{
     const genesis=JSON.parse(fs.readFileSync(file,'utf8'));
     if(!genesis||typeof genesis!=='object'||Array.isArray(genesis)||genesis.chain_id!==m.chain_id)errors.push('genesis chain_id does not match manifest');
    }catch(e){errors.push('invalid genesis JSON: '+e.message);}
   }
  }catch(e){errors.push('unreadable artifact: '+field+' ('+e.code+')');}
 }
 return errors;
}
if(require.main===module){
 const [manifest,genesis,binary]=process.argv.slice(2);
 if(!manifest||!genesis||!binary){console.error('Usage: node verify_artifacts.cjs manifest.json genesis.json validator-binary');process.exitCode=2;}
 else try{
  const m=JSON.parse(fs.readFileSync(path.resolve(manifest),'utf8'));
  const errors=verify(m,{genesis,binary});
  if(errors.length){console.error('NO-GO: '+errors.join('; '));process.exitCode=1;}
  else console.log('Local artifact hashes match manifest; signoffs, audit, chain identity, and launch readiness NOT independently verified. NO LAUNCH AUTHORIZED.');
 }catch(e){console.error('NO-GO: '+e.message);process.exitCode=1;}
}
module.exports={verify};
