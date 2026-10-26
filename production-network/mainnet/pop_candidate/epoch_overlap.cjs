"use strict";
/*
 * RESEARCH-ONLY necessary overlap preflight for candidate PoP committee epochs.
 * This is a mathematical quorum-intersection study, NOT joint consensus, a
 * transition certificate, governance approval, a deployed BFT implementation,
 * or authorization to enable native PRVI mainnet.
 *
 * Assumes fault counts at most floor((N-1)/3) for EACH candidate epoch
 * and that genuine shared validator identities use durable non-equivocation
 * locks. These assumptions are NOT established on any live network.
 */
const {assertValidatedCommittee} = require("./engine.cjs");

function requireCondition(ok, reason) {
  if(!ok) throw Error(reason);
}
function stableIdentity(validator) {
  // A key reused with changed operator/fault-domain/PoP position evidence
  // is NOT counted as an independently established common signer.
  return [
    validator.id,validator.operatorId,validator.faultDomain,
    validator.stamp,validator.positionHash,validator.anchorBlockHash
  ];
}
function analyzeEpochOverlap(previous, next) {
  assertValidatedCommittee(previous);
  assertValidatedCommittee(next);
  requireCondition(previous !== next,
    "PoP epoch preflight requires distinct admitted research committees");
  requireCondition(previous.chainId === next.chainId &&
                   previous.genesisHash === next.genesisHash,
    "PoP epoch preflight rejects chain or genesis identity changes");
  requireCondition(previous.governanceKeyId === next.governanceKeyId,
    "PoP governance authority change requires separately reviewed root handoff");
  requireCondition(BigInt(next.epoch) === BigInt(previous.epoch)+1n,
    "PoP epoch preflight requires exactly one forward epoch");

  const oldById = new Map(previous.validators.map(v=>[v.id,v]));
  let shared=0;
  for(const updated of next.validators) {
    const old=oldById.get(updated.id);
    if(old && JSON.stringify(stableIdentity(old)) ===
              JSON.stringify(stableIdentity(updated))) shared++;
  }
  const nOld=previous.validators.length,nNew=next.validators.length;
  const maxFaulty=Math.max(Math.floor((nOld-1)/3),Math.floor((nNew-1)/3));
  // Two quorums Qold, Qnew within a union of nOld+nNew-shared voters
  // overlap in at least |Qold|+|Qnew|-|union|. More than maxFaulty
  // common signers is a NECESSARY research safety check, not sufficient
  // proof of safe reconfiguration or honest-node state handoff.
  const union=nOld+nNew-shared;
  const guaranteedCommon=Math.max(0,previous.quorum+next.quorum-union);
  requireCondition(guaranteedCommon > maxFaulty,
    "PoP unsafe cross-epoch quorum overlap: possible disjoint honest quorums");

  return Object.freeze({
    researchOnly:true,
    overlapNecessaryCondition:true,
    permitsEpochTransition:false,
    productionConsensus:false,
    chainId:previous.chainId,fromEpoch:previous.epoch,toEpoch:next.epoch,
    priorValidators:nOld,nextValidators:nNew,unchangedSigners:shared,
    minimalCommonQuorumSigners:guaranteedCommon,
    assumedMaxFaultySharedSigners:maxFaulty,
    warning:"No finalized handoff proof, validator recovery, PoP ledger binding, or active network consensus"
  });
}
module.exports={analyzeEpochOverlap};
