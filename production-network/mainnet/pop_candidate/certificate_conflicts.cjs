"use strict";
/*
 * PRVI Point of Position candidate double-sign evidence research.
 *
 * This does NOT implement BFT finality, slashing, operator attribution,
 * production validator decisions, financial mainnet activation, or anything
 * that changes a node, key, wallet, balance, or active chain.
 *
 * It proves only that supplied individually verifiable PoP research quorum
 * certificates include at least one Ed25519 key that signed contradictory
 * block or parent-hash commitments at the same chain/genesis/epoch/height.
 * Keys might be copied/compromised. Absence of evidence in a supplied pair
 * does NOT prove the signer never equivocated elsewhere.
 */
const {
  verifyCertificate,assertValidatedCommittee,proposalFields,voteFields
}=require("./engine.cjs");

function need(ok,message){if(!ok)throw Error(message);}

// Capture authenticated evidence from own data descriptors exactly once.
// Never re-read caller-controlled getters, Proxy get traps or iterators after
// signature verification: the report must describe the SAME signed bytes.
function snapshotRecord(value,fields,label,allowMarker=false) {
  need(value && typeof value==="object" && !Array.isArray(value) &&
       Object.getPrototypeOf(value)===Object.prototype,
       "Noncanonical PoP research "+label);
  const keys=Reflect.ownKeys(value);
  const marker=allowMarker && Object.getOwnPropertyDescriptor(value,"researchOnly");
  const hasMarker=!!marker;
  need(keys.length===fields.length+(hasMarker?1:0) &&
       (!hasMarker || (Object.hasOwn(marker,"value") &&
         marker.value===true && marker.enumerable)),
       "Noncanonical PoP research "+label);
  const out={};
  for(const field of fields){
    const d=Object.getOwnPropertyDescriptor(value,field);
    need(d && Object.hasOwn(d,"value") && d.enumerable,
         "Noncanonical PoP research "+label);
    out[field]=d.value;
  }
  if(hasMarker)out.researchOnly=true;
  return out;
}
function snapshotCertificate(committee,input) {
  const envelope=snapshotRecord(input,["proposal","votes"],"certificate");
  const proposal=snapshotRecord(envelope.proposal,
    ["height","round","previousBlockHash","blockHash","proposerId","signature"],
    "proposal");
  const votes=envelope.votes;
  need(Array.isArray(votes) && Object.getPrototypeOf(votes)===Array.prototype,
       "Noncanonical PoP research votes");
  const length=Object.getOwnPropertyDescriptor(votes,"length")?.value;
  need(Number.isSafeInteger(length) && length>=0 &&
       length<=committee.validators.length &&
       Reflect.ownKeys(votes).length===length+1,
       "Noncanonical PoP research votes");
  const copied=[];
  for(let i=0;i<length;i++){
    const d=Object.getOwnPropertyDescriptor(votes,String(i));
    need(d && Object.hasOwn(d,"value") && d.enumerable,
         "Noncanonical PoP research votes");
    copied.push(snapshotRecord(d.value,["validatorId","signature"],
                               "vote",true));
  }
  return {proposal,votes:copied};
}

function verifyResearchCertificatePair(committee,left,right) {
  assertValidatedCommittee(committee);
  // Snapshots are plain data objects, so subsequent reads cannot change
  // the signer set or the bytes used to construct double-sign evidence.
  const firstInput=snapshotCertificate(committee,left);
  const secondInput=snapshotCertificate(committee,right);

  // These verify the entire signed proposal, each signer, epoch, round,
  // chain/genesis, per-certificate uniqueness, and quorum before any report.
  const first=verifyCertificate(committee,firstInput.proposal,firstInput.votes);
  const second=verifyCertificate(committee,secondInput.proposal,secondInput.votes);
  need(first.height===second.height,
       "PoP conflicting certificates must refer to the same height");

  const differentBlock=firstInput.proposal.blockHash!==secondInput.proposal.blockHash;
  const differentParent=
    firstInput.proposal.previousBlockHash!==secondInput.proposal.previousBlockHash;
  // Changing the *round alone* without changing block or parent does not
  // violate the persistent research height lock.
  const incompatible=differentBlock||differentParent;
  const secondSigners=new Map(secondInput.votes.map(v=>[v.validatorId,v]));
  // Signer fingerprints are fixed-width lowercase ASCII hex. Evidence order
  // must not depend on host ICU locale or environment language settings.
  const intersection=firstInput.votes.filter(v=>secondSigners.has(v.validatorId))
    .sort((a,b)=>a.validatorId < b.validatorId ? -1 :
                 a.validatorId > b.validatorId ? 1 : 0);

  // Two supermajority quorums in one admitted committee mathematically
  // intersect, but this is checked explicitly as a defensive assertion.
  const expectedMinimum=Math.max(0,2*committee.quorum-committee.validators.length);
  need(intersection.length>=expectedMinimum,
       "PoP certificate intersection is below required quorum overlap");

  const leftFields=proposalFields(committee,firstInput.proposal.height,
    firstInput.proposal.round,firstInput.proposal.previousBlockHash,
    firstInput.proposal.blockHash,firstInput.proposal.proposerId);
  const rightFields=proposalFields(committee,secondInput.proposal.height,
    secondInput.proposal.round,secondInput.proposal.previousBlockHash,
    secondInput.proposal.blockHash,secondInput.proposal.proposerId);

  // Preserve all signed fields and BOTH independently verified signatures,
  // sufficient to reproduce the signed-message verification offline given
  // the governance-admitted registry + pinned research governance key.
  const doubleSignEvidence=incompatible ? intersection.map(v=>{
    const other=secondSigners.get(v.validatorId);
    return Object.freeze({
      validatorId:v.validatorId,
      first:Object.freeze({
        voteFields:Object.freeze(voteFields(leftFields,v.validatorId)),
        signatureB64:v.signature
      }),
      second:Object.freeze({
        voteFields:Object.freeze(voteFields(rightFields,v.validatorId)),
        signatureB64:other.signature
      })
    });
  }):[];
  Object.freeze(doubleSignEvidence);

  return Object.freeze({
    researchOnly:true,
    productionConsensus:false,
    finalityProven:false,
    slashingAuthorized:false,
    operatorMisconductProven:false,
    certificateSignaturesVerified:true,
    chainId:committee.chainId,
    genesisHash:committee.genesisHash,
    epoch:committee.epoch,
    height:first.height,
    firstRound:first.round,secondRound:second.round,
    firstBlockHash:first.blockHash,
    secondBlockHash:second.blockHash,
    firstParentHash:firstInput.proposal.previousBlockHash,
    secondParentHash:secondInput.proposal.previousBlockHash,
    incompatibleCommitments:incompatible,
    intersectingSignerCount:intersection.length,
    minimumGuaranteedIntersection:expectedMinimum,
    doubleSignEvidence,
    warning:"Offline research only. Evidence that verified KEYS signed contradictory statements is not live PoP finality, identity attribution, authorization to slash, or proof of the absence of other forks."
  });
}
module.exports={verifyResearchCertificatePair};
