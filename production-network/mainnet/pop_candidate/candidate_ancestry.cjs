"use strict";
/*
 * Privi Point of Position candidate ancestry RESEARCH preflight.
 *
 * This is not a deployed blockchain, consensus state machine, actual
 * finality proof, trustworthy state root, or financial-mainnet approval.
 * A sequence of individually signed proposals alone is NOT enough:
 * the candidate chain must be contiguous from an independently pinned
 * external checkpoint, link each previousBlockHash, and stay inside the
 * same verified governance-admitted research committee and epoch.
 *
 * IMPORTANT: the checkpoint is caller-supplied, not independently
 * authenticated by this module. Production would require a finalized
 * chain-state proof, a secure checkpoint source and audited view changes.
 */
const {verifyCertificate,assertValidatedCommittee} = require("./engine.cjs");
const HASH=/^0x[0-9a-f]{64}$/;
const MAX_CERTIFICATES=256;

function need(ok,message){if(!ok)throw Error(message);}

function verifyCandidateAncestry(committee, checkpoint, certificates) {
  assertValidatedCommittee(committee);
  need(checkpoint && typeof checkpoint==="object" && !Array.isArray(checkpoint),
       "PoP research checkpoint object required");
  // Caller-supplied anchors must not obtain their fields from prototypes or
  // execute accessor code while the ancestry verifier checks signatures.
  // A Proxy may advertise valid own data descriptors yet return different
  // values through ordinary property reads. Only descriptor values are used.
  const anchor=Object.create(null);
  need(Object.getPrototypeOf(checkpoint)===Object.prototype &&
       Reflect.ownKeys(checkpoint).length===2 &&
       ["height","blockHash"].every(field=>{
         const descriptor=Object.getOwnPropertyDescriptor(checkpoint,field);
         if(!descriptor || !Object.hasOwn(descriptor,"value") ||
            !descriptor.enumerable) return false;
         anchor[field]=descriptor.value;
         return true;
       }),
       "PoP research checkpoint requires plain own height and blockHash data fields");
  const checkpointHeight=anchor.height,checkpointHash=anchor.blockHash;
  // JSON encodes -0 as 0; reject noncanonical zero in untrusted anchors.
  need(Number.isSafeInteger(checkpointHeight) && checkpointHeight>=0 &&
       !Object.is(checkpointHeight,-0),
       "PoP research checkpoint height must be a nonnegative safe integer");
  need(typeof checkpointHash==="string" && HASH.test(checkpointHash),
       "PoP research checkpoint hash must be a canonical 32-byte hash");
  // Read the declared array length from its descriptor, not a Proxy get trap.
  // Only the explicit certificate slots may contribute to signed ancestry.
  const lengthDescriptor=Array.isArray(certificates) &&
    Object.getOwnPropertyDescriptor(certificates,"length");
  const certificateCount=lengthDescriptor && lengthDescriptor.value;
  need(Number.isSafeInteger(certificateCount) && certificateCount>=1 &&
       certificateCount<=MAX_CERTIFICATES,
       "PoP research certificate list must contain 1..256 entries");

  // The certificate batch is untrusted, unsigned input. Reject inherited
  // array prototypes, hidden/symbolic metadata, holes, and index getters
  // before .entries() can execute an attacker-controlled accessor.
  need(Object.getPrototypeOf(certificates)===Array.prototype &&
       Reflect.ownKeys(certificates).length===certificateCount+1,
       "PoP research certificate batch requires a dense plain data array without metadata or accessors");
  // Snapshot each validated own data descriptor exactly once. Array.entries()
  // and index reads can be overridden by a Proxy to inject different proofs.
  const canonicalCertificates=[];
  for(let i=0;i<certificateCount;i++){
    const descriptor=Object.getOwnPropertyDescriptor(certificates,String(i));
    need(descriptor && Object.hasOwn(descriptor,"value") && descriptor.enumerable,
         "PoP research certificate batch requires a dense plain data array without metadata or accessors");
    canonicalCertificates.push(descriptor.value);
  }

  let height=checkpointHeight,head=checkpointHash;
  let lastRound=0;
  let signedVotes=0;
  const heights=new Set(), hashes=new Set([head]);
  // Use numeric slots, not an inherited Array.prototype.entries method.
  for(let index=0;index<canonicalCertificates.length;index++) {
    const certificate=canonicalCertificates[index];
    need(certificate && typeof certificate==="object" && !Array.isArray(certificate),
         "PoP malformed research certificate at index "+index);
    // The envelope may be a Proxy whose get trap returns different proofs
    // than the own data descriptors that passed structural validation.
    const envelope=Object.create(null);
    need(Object.getPrototypeOf(certificate)===Object.prototype &&
         Reflect.ownKeys(certificate).length===2 &&
         ["proposal","votes"].every(field=>{
           const descriptor=Object.getOwnPropertyDescriptor(certificate,field);
           if(!descriptor || !Object.hasOwn(descriptor,"value") ||
              !descriptor.enumerable) return false;
           envelope[field]=descriptor.value;
           return true;
         }),
         "PoP research certificate requires plain own proposal and votes data fields");
    const {proposal,votes}=envelope;
    need(proposal && typeof proposal==="object" && !Array.isArray(proposal),
         "PoP missing candidate proposal at index "+index);

    // Check continuity using the signed proposal's own data descriptors.
    // Keep these pre-verification error boundaries for malformed ancestry,
    // without allowing Proxy get traps to invent a different parent/height.
    const signed=Object.create(null);
    for(const field of ["height","round","previousBlockHash","blockHash"]){
      const descriptor=Object.getOwnPropertyDescriptor(proposal,field);
      need(descriptor && Object.hasOwn(descriptor,"value") &&
           descriptor.enumerable,
           "PoP research candidate requires own signed data fields");
      signed[field]=descriptor.value;
    }
    need(height<Number.MAX_SAFE_INTEGER && signed.height===height+1,
         "PoP research certificate height gap, rollback or reorder at index "+index);
    need(signed.previousBlockHash===head,
         "PoP research certificate parent hash mismatch at index "+index);
    need(!heights.has(signed.height),
         "PoP research duplicate height at index "+index);
    need(!hashes.has(signed.blockHash),
         "PoP research duplicate or cyclic block hash at index "+index);

    // Only verified Ed25519 proposal/quorum metadata may update ancestry.
    const checked=verifyCertificate(committee,proposal,votes);
    need(checked.valid===true && checked.productionConsensus===false &&
         checked.chainId===committee.chainId && checked.epoch===committee.epoch &&
         checked.height===signed.height && checked.round===signed.round &&
         checked.previousBlockHash===signed.previousBlockHash &&
         checked.blockHash===signed.blockHash,
         "PoP malformed signed candidate proof at index "+index);
    heights.add(checked.height);
    hashes.add(checked.blockHash);
    height=checked.height;
    head=checked.blockHash;
    lastRound=checked.round;
    signedVotes+=checked.signers;
  }
  return Object.freeze({
    researchOnly:true,
    productionConsensus:false,
    finalized:false,
    verifiesExecution:false,
    verifiesCheckpointAuthenticity:false,
    chainId:committee.chainId,
    epoch:committee.epoch,
    governanceKeyId:committee.governanceKeyId,
    checkpointHeight,
    checkpointHash,
    endingHeight:height,
    endingBlockHash:head,
    endingRound:lastRound,
    verifiedCandidateCertificates:canonicalCertificates.length,
    checkedSignatures:signedVotes,
    warning:"Only validates local signed research candidates against a CALLER-SUPPLIED checkpoint; not canonical chain state or native financial finality"
  });
}
module.exports={verifyCandidateAncestry,MAX_CERTIFICATES};
