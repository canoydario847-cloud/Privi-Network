'use strict';
// Privi Wall receipt transcript v1. This is a digest, NOT a digital signature.
// A trusted signer must sign the returned bytes with an approved algorithm.
const {createHash}=require('node:crypto');
const DOMAIN=Buffer.from('PRIVI-WALL-AGENT-EXECUTION-RECEIPT-V1\0','utf8');
const ID=/^[A-Za-z0-9_-]{1,64}$/;
function receiptTranscript(fields){
 if(!fields||typeof fields!=='object'||Array.isArray(fields))throw TypeError('receipt');
 const names=['tenant','agent','action','nonce','requestSha256','outcomeSha256','keyId'];
 const out=Object.create(null);
 for(const k of names){
  if(!Object.hasOwn(fields,k)||typeof fields[k]!=='string')throw TypeError(k);
  out[k]=fields[k];
 }
 for(const k of ['tenant','agent','action','keyId'])if(!ID.test(out[k]))throw TypeError(k);
 if(!/^[a-f0-9]{32,128}$/.test(out.nonce))throw TypeError('nonce');
 for(const k of ['requestSha256','outcomeSha256'])if(!/^[a-f0-9]{64}$/.test(out[k]))throw TypeError(k);
 if(!Number.isSafeInteger(fields.executedAt)||fields.executedAt<0)throw TypeError('executedAt');
 if(fields.status!=='success'&&fields.status!=='failure')throw TypeError('status');
 // Fixed-order length-prefixed UTF-8 fields eliminate separator ambiguities.
 const values=[...names.map(k=>out[k]),String(fields.executedAt),fields.status];
 const chunks=[DOMAIN];
 for(const value of values){const b=Buffer.from(value,'utf8'),n=Buffer.alloc(4);n.writeUInt32BE(b.length);chunks.push(n,b);}
 return Buffer.concat(chunks);
}
function receiptDigest(fields){return createHash('sha256').update(receiptTranscript(fields)).digest('hex');}
module.exports={receiptTranscript,receiptDigest};
