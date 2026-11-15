"use strict";
// RESEARCH ONLY. Binds available opaque transaction bytes to a candidate hash.
// Does not execute transactions, validate balances, prove network availability,
// provide fork choice, or install production consensus.
const {hash, signedMessage, verifyProposal, TRUSTED_MODE} = require("./engine.cjs");
const {signCommitWithResearchLock} = require("./persistent_vote_guard.cjs");
const MAX_TRANSACTIONS = 1024;
const MAX_TRANSACTION_BYTES = 65536;
const MAX_BLOCK_BYTES = 1048576;
const HASH = /^0x[0-9a-f]{64}$/;
function must(ok, message) { if (!ok) throw Error(message); }

function researchBlockHash(committee, block) {
  must(committee?.mode === TRUSTED_MODE &&
    typeof committee.chainId === "string" &&
    /^privi-pop-research-[a-z0-9-]{1,48}$/.test(committee.chainId) &&
    typeof committee.genesisHash === "string" && HASH.test(committee.genesisHash) &&
    Number.isSafeInteger(committee.epoch) && committee.epoch > 0,
    "Research block requires pinned research committee");
  must(block && typeof block === "object" && !Array.isArray(block) &&
    Object.keys(block).sort().join(",") === "height,previousBlockHash,transactions",
    "Research block must contain exactly height, previousBlockHash, transactions");
  const {height, previousBlockHash, transactions} = block;
  must(Number.isSafeInteger(height) && height > 0, "Invalid research block height");
  must(typeof previousBlockHash === "string" && HASH.test(previousBlockHash),
    "Invalid research block parent");
  must(Array.isArray(transactions) && transactions.length <= MAX_TRANSACTIONS,
    "Research block transaction count exceeds limit or is malformed");
  let total = 0;
  const committed = [];
  for (const encoded of transactions) {
    must(typeof encoded === "string" && encoded.length > 0 &&
      encoded.length <= 4 * Math.ceil(MAX_TRANSACTION_BYTES / 3) &&
      /^[A-Za-z0-9+/]+={0,2}$/.test(encoded), "Invalid research transaction encoding or size");
    const bytes = Buffer.from(encoded, "base64");
    must(bytes.length <= MAX_TRANSACTION_BYTES && bytes.toString("base64") === encoded,
      "Research transaction must use canonical base64 within size limit");
    total += bytes.length;
    must(total <= MAX_BLOCK_BYTES, "Research block byte limit exceeded");
    committed.push(encoded);
  }
  // Fixed array order includes all block context and ordered transaction bytes.
  // Round and proposer stay in the signed proposal, allowing the same payload
  // to be proposed again in another round without changing its block identity.
  return hash(signedMessage("block-payload-v1", [committee.chainId,
    committee.genesisHash, committee.epoch, height, previousBlockHash, committed]));
}

function verifyResearchBlockProposal(committee, proposal, block) {
  verifyProposal(committee, proposal);
  const blockHash = researchBlockHash(committee, block);
  must(block.height === proposal.height &&
    block.previousBlockHash === proposal.previousBlockHash &&
    blockHash === proposal.blockHash, "Research block payload does not match signed proposal");
  return Object.freeze({blockHash, researchOnly:true, executionVerified:false,
    productionConsensus:false});
}

function signCommitWithResearchBlock({lockDirectory, committee, proposal, block, privateKey}) {
  // Validate body and signature before creating a persistent reservation.
  verifyResearchBlockProposal(committee, proposal, block);
  return signCommitWithResearchLock({lockDirectory, committee, proposal, privateKey});
}

module.exports = {researchBlockHash, verifyResearchBlockProposal,
  signCommitWithResearchBlock, MAX_TRANSACTIONS, MAX_TRANSACTION_BYTES, MAX_BLOCK_BYTES};
