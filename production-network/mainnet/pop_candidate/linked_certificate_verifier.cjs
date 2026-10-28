"use strict";
/*
 * Research-only: deterministic read-only validation of a contiguous sequence
 * of signed PoP candidate certificates against an EXTERNALLY TRUSTED anchor.
 *
 * This is NOT consensus, finality, an authenticated chain-state proof, a
 * production light client, or integration with CometBFT/Cosmos EVM.
 * A caller-supplied non-genesis anchor is NOT verified by this module.
 */
const {verifyCertificate, TRUSTED_MODE} = require("./engine.cjs");

const HASH = /^0x[0-9a-f]{64}$/;
const MAX_BATCH = 128;
function requireValid(condition, message) {
  if (!condition) throw new Error(message);
}
function verifyLinkedResearchCertificates({committee, anchorHeight, anchorHash, bundles} = {}) {
  requireValid(committee && committee.mode === TRUSTED_MODE,
    "PoP linked certificates require research-only committee");
  requireValid(Array.isArray(bundles) && bundles.length >= 1 &&
    bundles.length <= MAX_BATCH, "Research certificate batch must contain 1..128 blocks");
  requireValid(Number.isSafeInteger(anchorHeight) && anchorHeight >= 0 &&
    anchorHeight <= Number.MAX_SAFE_INTEGER - bundles.length,
    "Invalid research anchor height");
  requireValid(typeof anchorHash === "string" && HASH.test(anchorHash),
    "Invalid research anchor block hash");
  requireValid(typeof committee.genesisHash === "string" && HASH.test(committee.genesisHash),
    "Missing pinned research genesis");
  // Height zero must be pinned to the committee's signed genesis identity.
  // Non-genesis anchors must be authenticated externally, never by this tool.
  if (anchorHeight === 0) {
    requireValid(anchorHash === committee.genesisHash,
      "Research genesis anchor does not match committee identity");
  }
  const checked = [];
  // A signed but repeated block identity is not a valid linear history.
  // Include the anchor to reject a return to an already accepted block.
  const seenBlockHashes = new Set([anchorHash]);
  let parent = anchorHash;
  let height = anchorHeight;
  for (const item of bundles) {
    requireValid(item && typeof item === "object" && !Array.isArray(item) &&
      item.proposal && typeof item.proposal === "object" && Array.isArray(item.votes),
      "Malformed research certificate bundle");
    requireValid(item.proposal.height === height + 1,
      "Research certificate height gap, duplicate or reordering");
    requireValid(item.proposal.previousBlockHash === parent,
      "Research certificate parent link mismatch");
    // Every block is signature-checked under the SAME pinned committee.
    // No membership/epoch transition or view change is inferred here.
    const certificate = verifyCertificate(committee, item.proposal, item.votes);
    requireValid(!seenBlockHashes.has(certificate.blockHash),
      "Research certificate repeats an earlier block hash");
    seenBlockHashes.add(certificate.blockHash);
    checked.push(Object.freeze({
      height: certificate.height,
      round: certificate.round,
      blockHash: certificate.blockHash,
      signers: certificate.signers,
      quorum: certificate.quorum,
    }));
    height = certificate.height;
    parent = certificate.blockHash;
  }
  return Object.freeze({
    researchOnly: true,
    productionConsensus: false,
    productionFinality: false,
    anchorTrustVerified: false,
    chainId: committee.chainId,
    genesisHash: committee.genesisHash,
    epoch: committee.epoch,
    anchorHeight,
    anchorHash,
    lastHeight: height,
    lastBlockHash: parent,
    checked: Object.freeze(checked),
  });
}

module.exports = {verifyLinkedResearchCertificates};
