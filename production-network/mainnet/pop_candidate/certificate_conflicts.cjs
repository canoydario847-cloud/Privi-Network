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

function verifyResearchCertificatePair(committee,left,right) {
  assertValidatedCommittee(committee);
  need(left && typeof left==="object" && !Array.isArray(left) &&
       right && typeof right==="object" && !Array.isArray(right),
       "PoP research conflict audit requires two certificate objects");
  need(left.proposal && typeof left.proposal==="object" &&
       right.proposal && typeof right.proposal==="object",
       "PoP research certificate missing proposal");

  // These verify the entire signed proposal, each signer, epoch, round,
  // chain/genesis, per-certificate uniqueness, and quorum before any report.
  const first=verifyCertificate(committee,left.proposal,left.votes);
  const second=verifyCertificate(committee,right.proposal,right.votes);
  need(first.height===second.height,
       "PoP conflicting certificates must refer to the same height");

  const differentBlock=left.proposal.blockHash!==right.proposal.blockHash;
  const differentParent=
    left.proposal.previousBlockHash!==right.proposal.previousBlockHash;
  // Changing the *round alone* without changing block or parent does not
  // violate the persistent research height lock.
  const incompatible=differentBlock||differentParent;
  const secondSigners=new Map(right.votes.map(v=>[v.validatorId,v]));
  // Signer fingerprints are fixed-width lowercase ASCII hex. Evidence order
  // must not depend on host ICU locale or environment language settings.
  const intersection=left.votes.filter(v=>secondSigners.has(v.validatorId))
    .sort((a,b)=>a.validatorId < b.validatorId ? -1 :
                 a.validatorId > b.validatorId ? 1 : 0);

  // Two supermajority quorums in one admitted committee mathematically
  // intersect, but this is checked explicitly as a defensive assertion.
  const expectedMinimum=Math.max(0,2*committee.quorum-committee.validators.length);
  need(intersection.length>=expectedMinimum,
       "PoP certificate intersection is below required quorum overlap");

  const leftFields=proposalFields(committee,left.proposal.height,
    left.proposal.round,left.proposal.previousBlockHash,
    left.proposal.blockHash,left.proposal.proposerId);
  const rightFields=proposalFields(committee,right.proposal.height,
    right.proposal.round,right.proposal.previousBlockHash,
    right.proposal.blockHash,right.proposal.proposerId);

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
    firstParentHash:left.proposal.previousBlockHash,
    secondParentHash:right.proposal.previousBlockHash,
    incompatibleCommitments:incompatible,
    intersectingSignerCount:intersection.length,
    minimumGuaranteedIntersection:expectedMinimum,
    doubleSignEvidence,
    warning:"Offline research only. Evidence that verified KEYS signed contradictory statements is not live PoP finality, identity attribution, authorization to slash, or proof of the absence of other forks."
  });
}
module.exports={verifyResearchCertificatePair};
