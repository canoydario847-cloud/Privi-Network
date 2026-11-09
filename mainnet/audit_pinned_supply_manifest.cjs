'use strict';
// Offline integrity gate only. A digest is NOT authorization: obtain expected SHA-256
// independently from an approved, authenticated release record (never from the file).
const {createHash,timingSafeEqual}=require('node:crypto');
const {auditSupplyManifest}=require('./audit_supply_manifest.cjs');
const SHA256=/^[0-9a-f]{64}$/;
function auditPinnedSupplyManifest(genesis, manifestBytes, approvedSha256) {
 const errors=[];
 if(typeof approvedSha256!=='string'||!SHA256.test(approvedSha256))
  return ['missing or invalid independently approved SHA-256 digest'];
 if(!Buffer.isBuffer(manifestBytes)||manifestBytes.length===0||manifestBytes.length>1024*1024)
  return ['manifest must be nonempty raw bytes no larger than 1 MiB'];
 const actual=createHash('sha256').update(manifestBytes).digest();
 if(!timingSafeEqual(actual,Buffer.from(approvedSha256,'hex')))
  return ['manifest SHA-256 differs from independently approved digest'];
 let manifest;
 try { manifest=JSON.parse(manifestBytes.toString('utf8')); }
 catch {return ['manifest JSON is invalid'];}
 errors.push(...auditSupplyManifest(genesis,manifest));
 return errors;
}
module.exports={auditPinnedSupplyManifest};
