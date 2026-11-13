#!/usr/bin/env node
'use strict';
// Offline, fail-closed native PRVI mainnet readiness gate. No network or wallet operations.
const fs=require('node:fs');
const path=require('node:path');
const REQUIRED=['chain_id','genesis_sha256','binary_sha256','validator_signoffs','audit_approval','rehearsal_report','rollback_plan'];
function check(m){
 const errors=[];
 if(!m||typeof m!=='object'||Array.isArray(m))return ['manifest must be an object'];
 for(const k of REQUIRED)if(!(k in m))errors.push('missing '+k);
 if(typeof m.chain_id!=='string'||!/^privi-[a-z0-9-]{3,50}$/.test(m.chain_id))errors.push('invalid chain_id');
 for(const k of ['genesis_sha256','binary_sha256'])if(typeof m[k]!=='string'||!/^[a-f0-9]{64}$/.test(m[k]))errors.push('invalid '+k);
 if(!Array.isArray(m.validator_signoffs)||m.validator_signoffs.length<4||new Set(m.validator_signoffs.map(x=>x?.validator_id)).size!==m.validator_signoffs.length||m.validator_signoffs.some(x=>!x||typeof x.validator_id!=='string'||!x.validator_id||typeof x.signature_reference!=='string'||!x.signature_reference))errors.push('need four distinct validator signoff references');
 for(const k of ['audit_approval','rehearsal_report','rollback_plan'])if(typeof m[k]!=='string'||!m[k].trim())errors.push('missing evidence '+k);
 return errors;
}
if(require.main===module){
 const file=process.argv[2];
 if(!file){console.error('Usage: node readiness.cjs manifest.json');process.exitCode=2;}
 else try{const m=JSON.parse(fs.readFileSync(path.resolve(file),'utf8'));const e=check(m);if(e.length){console.error('NO-GO: '+e.join('; '));process.exitCode=1;}else{console.log('Manifest structure complete; NOT an independent verification of evidence. NO LAUNCH AUTHORIZED.');process.exitCode=0;}}catch(e){console.error('NO-GO: '+e.message);process.exitCode=1;}
}
module.exports={check};
