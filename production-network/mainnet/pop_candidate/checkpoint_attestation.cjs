"use strict";
/*
 * Synthetic-only Privi Point of Position research checkpoint issuer verification.
 * It authenticates a signed assertion against an independently provided and
 * pinned governance Ed25519 public key. Neither a signature nor the governance
 * authority proves canonical block state, execution, BFT safety or finality.
 *
 * This module does NOT run consensus, create validators, activate native PRVI,
 * issue coins or use any live keys. Never advertise this as a finalized state
 * proof or production checkpoint.
 */
const crypto=require("node:crypto");
const {
  assertValidatedCommittee,publicKey,signedMessage
}=require("./engine.cjs");
const {verifyCandidateAncestry}=require("./candidate_ancestry.cjs");
const SCHEMA="PriviPoPResearchGovernanceCheckpoint/v1";
const MODE="research-attestation-not-chain-finality";
const SIGNING_TAG="research-checkpoint-attestation-v1";
const HASH=/^0x[0-9a-f]{64}$/;
const REQUIRED_FIELDS=[
  "schema","mode","chainId","genesisHash","epoch","height",
  "blockHash","governanceKeyId","signatureB64"
];

function need(value,reason){if(!value)throw Error(reason);}

function checkpointFields(checkpoint){
  return [
    checkpoint.schema,checkpoint.mode,checkpoint.chainId,
    checkpoint.genesisHash,checkpoint.epoch,checkpoint.height,
    checkpoint.blockHash,checkpoint.governanceKeyId
  ];
}
function verifyResearchCheckpoint(committee,checkpoint,trustedGovernancePublicKey){
  assertValidatedCommittee(committee);
  need(checkpoint && typeof checkpoint==="object" &&
       !Array.isArray(checkpoint) &&
       Object.getPrototypeOf(checkpoint)===Object.prototype,
       "PoP research signed checkpoint object required");
  need(Object.keys(checkpoint).length===REQUIRED_FIELDS.length &&
       REQUIRED_FIELDS.every(field=>Object.hasOwn(checkpoint,field)),
       "PoP signed checkpoint has missing or unexpected fields");
  need(checkpoint.schema===SCHEMA && checkpoint.mode===MODE,
       "PoP research checkpoint must not claim production finality");
  need(checkpoint.chainId===committee.chainId &&
       checkpoint.genesisHash===committee.genesisHash &&
       checkpoint.epoch===committee.epoch,
       "PoP signed checkpoint belongs to another chain, genesis or epoch");
  need(Number.isSafeInteger(checkpoint.height) && checkpoint.height>=0 &&
       checkpoint.height<Number.MAX_SAFE_INTEGER,
       "PoP signed checkpoint height must be a nonnegative bounded integer");
  need(typeof checkpoint.blockHash==="string" && HASH.test(checkpoint.blockHash),
       "PoP signed checkpoint requires canonical block hash");

  // This key must come from an independent evaluator's pinned trust source,
  // not simply copied from the untrusted checkpoint or PR metadata.
  const trusted=publicKey(trustedGovernancePublicKey);
  need(trusted.id===committee.governanceKeyId &&
       checkpoint.governanceKeyId===trusted.id,
       "PoP checkpoint signer is not the independently trusted committee authority");
  const encoded=checkpoint.signatureB64;
  need(typeof encoded==="string" &&
       /^[A-Za-z0-9+/]+={0,2}$/.test(encoded),
       "PoP checkpoint signature missing or not base64");
  const signature=Buffer.from(encoded,"base64");
  need(signature.length===64 && signature.toString("base64")===encoded,
       "PoP checkpoint Ed25519 signature must be canonical");
  need(crypto.verify(null,signedMessage(SIGNING_TAG,checkpointFields(checkpoint)),
                     trusted.key,signature),
       "PoP signed checkpoint issuer signature invalid");
  return Object.freeze({
    researchOnly:true,
    checkpointIssuerSignatureVerified:true,
    checkpointFinalityVerified:false,
    productionConsensus:false,
    chainId:checkpoint.chainId,
    genesisHash:checkpoint.genesisHash,
    epoch:checkpoint.epoch,
    governanceKeyId:trusted.id,
    height:checkpoint.height,
    blockHash:checkpoint.blockHash,
    warning:"This authenticates a research governance CLAIM; not a finalized canonical block or a secure externally pinned trust root"
  });
}
function verifyAttestedCandidateAncestry(committee,checkpoint,
                                        trustedGovernancePublicKey,certificates){
  const signedCheckpoint=verifyResearchCheckpoint(committee,checkpoint,
                                                  trustedGovernancePublicKey);
  const ancestry=verifyCandidateAncestry(committee,{
    height:signedCheckpoint.height,blockHash:signedCheckpoint.blockHash
  },certificates);
  return Object.freeze({
    ...ancestry,
    checkpointIssuerSignatureVerified:true,
    checkpointFinalityVerified:false,
    verifiesCheckpointAuthenticity:false,
    productionConsensus:false,
    finalized:false,
    warning:"Valid signature over a GOVERNANCE ASSERTION and contiguous candidate votes; no external canonical-state attestation, BFT finality, or production authority"
  });
}
module.exports={
  SCHEMA,MODE,SIGNING_TAG,checkpointFields,verifyResearchCheckpoint,
  verifyAttestedCandidateAncestry
};
