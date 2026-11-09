'use strict';
// Privi Wall receipt verification v1: explicit algorithm policy, no implicit trust.
// Classical Ed25519 is NOT post-quantum. Add ML-DSA only after validated interoperability.
const {verify, createPublicKey, KeyObject}=require('node:crypto');
const {receiptTranscript}=require('./receipt_transcript.cjs');
const KEY_ID=/^[A-Za-z0-9_-]{1,64}$/;
function verifyExecutionReceipt({receipt,signature,algorithm,keyResolver}={}){
 try {
  if(algorithm!=='Ed25519'||!receipt||typeof receipt!=='object'||Array.isArray(receipt)||
     typeof keyResolver!=='function'||!Buffer.isBuffer(signature)||signature.length!==64||
     !Object.hasOwn(receipt,'keyId')||typeof receipt.keyId!=='string'||
     !KEY_ID.test(receipt.keyId))return false;
  const transcript=receiptTranscript(receipt);
  const trusted=keyResolver(receipt.keyId,algorithm);
  // No caller-supplied public key, fallback key, or algorithm negotiation.
  if(!trusted||typeof trusted.then==='function')return false;
  const key=trusted instanceof KeyObject && trusted.type==='public' ? trusted : createPublicKey(trusted);
  if(key.asymmetricKeyType!=='ed25519')return false;
  return verify(null,transcript,key,signature);
 }catch(_){return false;}
}
module.exports={verifyExecutionReceipt};
