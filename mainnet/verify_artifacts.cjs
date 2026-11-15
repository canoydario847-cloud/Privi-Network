#!/usr/bin/env node
'use strict';
// Offline artifact integrity check. Does not attest to provenance or authorize launch.
const fs=require('node:fs');
const crypto=require('node:crypto');
const path=require('node:path');
const {check}=require('./readiness.cjs');
const MAX_GENESIS_BYTES=64*1024*1024;

// Hash a stable regular file through one descriptor. Never buffer an entire
// validator binary; genesis is bounded and the bytes parsed are those hashed.
function readArtifact(file, readGenesis){
 const fd=fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
 try {
  const before=fs.fstatSync(fd);
  if(!before.isFile()) throw Error('artifact is not a regular file');
  if(readGenesis && before.size>MAX_GENESIS_BYTES){
   const e=Error('genesis exceeds 64 MiB offline audit limit');
   e.code='PRIVI_GENESIS_OVERSIZE';
   throw e;
  }
  const hash=crypto.createHash('sha256'), buffer=Buffer.allocUnsafe(1024*1024);
  const chunks=readGenesis?[]:null;
  let n,total=0;
  while((n=fs.readSync(fd,buffer,0,buffer.length,null))>0){
   total+=n;
   if(readGenesis && total>MAX_GENESIS_BYTES){
    const e=Error('genesis exceeds 64 MiB offline audit limit');
    e.code='PRIVI_GENESIS_OVERSIZE';
    throw e;
   }
   const bytes=buffer.subarray(0,n);
   hash.update(bytes);
   if(chunks) chunks.push(Buffer.from(bytes));
  }
  const after=fs.fstatSync(fd);
  if(total!==before.size || total!==after.size || before.mtimeMs!==after.mtimeMs){
   throw Error('artifact changed during verification');
  }
  return {digest:hash.digest('hex'), genesisBytes:chunks?Buffer.concat(chunks,total):null};
 } finally {fs.closeSync(fd);}
}
function verify(m,files){
 const errors=check(m);
 if(errors.length)return errors;
 for(const [field,file] of [['genesis_sha256',files.genesis],['binary_sha256',files.binary]]){
  if(typeof file!=='string'||!file.trim()){errors.push('missing artifact path for '+field);continue;}
  try{
   const stat=fs.lstatSync(file);
   if(!stat.isFile()||stat.isSymbolicLink()){errors.push('artifact is not a regular file: '+field);continue;}
   const result=readArtifact(file,field==='genesis_sha256');
   if(result.digest!==m[field])errors.push('digest mismatch: '+field);
   if(field==='genesis_sha256' && result.digest===m[field]){
    try{
     const genesis=JSON.parse(result.genesisBytes.toString('utf8'));
     if(!genesis||typeof genesis!=='object'||Array.isArray(genesis)||genesis.chain_id!==m.chain_id)errors.push('genesis chain_id does not match manifest');
    }catch(e){errors.push('invalid genesis JSON: '+e.message);}
   }
  }catch(e){
   errors.push(e.code==='PRIVI_GENESIS_OVERSIZE'
    ? 'genesis exceeds 64 MiB offline audit limit'
    : 'unreadable artifact: '+field+' ('+(e.code||e.message)+')');
  }
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
