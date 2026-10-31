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
  need(Object.getPrototypeOf(checkpoint)===Object.prototype &&
       Reflect.ownKeys(checkpoint).length===2 &&
       ["height","blockHash"].every(field=>{
         const descriptor=Object.getOwnPropertyDescriptor(checkpoint,field);
         return descriptor && Object.hasOwn(descriptor,"value") &&
                descriptor.enumerable;
       }),
       "PoP research checkpoint requires plain own height and blockHash data fields");
  // JSON encodes -0 as 0; reject noncanonical zero in untrusted anchors.
  need(Number.isSafeInteger(checkpoint.height) && checkpoint.height>=0 &&
       !Object.is(checkpoint.height,-0),
       "PoP research checkpoint height must be a nonnegative safe integer");
  need(typeof checkpoint.blockHash==="string" && HASH.test(checkpoint.blockHash),
       "PoP research checkpoint hash must be a canonical 32-byte hash");
  need(Array.isArray(certificates) && certificates.length>=1 &&
       certificates.length<=MAX_CERTIFICATES,
       "PoP research certificate list must contain 1..256 entries");

  // The certificate batch is untrusted, unsigned input. Reject inherited
  // array prototypes, hidden/symbolic metadata, holes, and index getters
  // before .entries() can execute an attacker-controlled accessor.
  need(Object.getPrototypeOf(certificates)===Array.prototype &&
       Reflect.ownKeys(certificates).length===certificates.length+1 &&
       Array.from({length:certificates.length},(_,i)=>{
         const descriptor=Object.getOwnPropertyDescriptor(certificates,String(i));
         return descriptor && Object.hasOwn(descriptor,"value") &&
                descriptor.enumerable;
       }).every(Boolean),
       "PoP research certificate batch requires a dense plain data array without metadata or accessors");

  let height=checkpoint.height,head=checkpoint.blockHash;
  let lastRound=0;
  let signedVotes=0;
  const heights=new Set(), hashes=new Set([head]);
  for(const [index,certificate] of certificates.entries()) {
    need(certificate && typeof certificate==="object" && !Array.isArray(certificate),
         "PoP malformed research certificate at index "+index);
    // A signed candidate envelope must not execute caller-supplied getters
    // or accept inherited, hidden or symbol-keyed finality metadata.
    need(Object.getPrototypeOf(certificate)===Object.prototype &&
         Reflect.ownKeys(certificate).length===2 &&
         ["proposal","votes"].every(field=>{
           const descriptor=Object.getOwnPropertyDescriptor(certificate,field);
           return descriptor && Object.hasOwn(descriptor,"value") &&
                  descriptor.enumerable;
         }),
         "PoP research certificate requires plain own proposal and votes data fields");
    const {proposal,votes}=certificate;
    need(proposal && typeof proposal==="object" && !Array.isArray(proposal),
         "PoP missing candidate proposal at index "+index);
    need(height<Number.MAX_SAFE_INTEGER && proposal.height===height+1,
         "PoP research certificate height gap, rollback or reorder at index "+index);
    need(proposal.previousBlockHash===head,
         "PoP research certificate parent hash mismatch at index "+index);
    need(!heights.has(proposal.height),
         "PoP research duplicate height at index "+index);
    need(!hashes.has(proposal.blockHash),
         "PoP research duplicate or cyclic block hash at index "+index);

    // Re-verify original Ed25519 votes, proposer, epoch, chain/genesis,
    // distinct quorum and exact candidate proposal at EVERY height.
    const checked=verifyCertificate(committee,proposal,votes);
    need(checked.valid===true && checked.productionConsensus===false &&
         checked.height===proposal.height && checked.blockHash===proposal.blockHash &&
         checked.chainId===committee.chainId && checked.epoch===committee.epoch,
         "PoP malformed signed candidate proof at index "+index);
    heights.add(proposal.height);
    hashes.add(proposal.blockHash);
    height=proposal.height;
    head=proposal.blockHash;
    lastRound=proposal.round;
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
    checkpointHeight:checkpoint.height,
    checkpointHash:checkpoint.blockHash,
    endingHeight:height,
    endingBlockHash:head,
    endingRound:lastRound,
    verifiedCandidateCertificates:certificates.length,
    checkedSignatures:signedVotes,
    warning:"Only validates local signed research candidates against a CALLER-SUPPLIED checkpoint; not canonical chain state or native financial finality"
  });
}
module.exports={verifyCandidateAncestry,MAX_CERTIFICATES};
