"use strict";
/*
 * Privi PoP multi-round RESEARCH state machine.
 *
 * Builds on engine.cjs proposal/commit certificates. This is NOT CometBFT,
 * NOT ABCI, NOT production PoP finality, and does NOT activate mainnet or PRVI.
 *
 * What it adds (still research):
 *   propose -> prevote -> precommit -> commit phases
 *   deterministic round timeouts (caller-driven)
 *   view-change to the next round when a phase lacks quorum
 *   in-memory locked value after a precommit quorum (same height)
 *
 * Explicitly absent: network transport, Byzantine view-change proofs across
 * partitions, crash-safe lock store (use persistent_vote_guard separately),
 * execution, and financial issuance.
 */
const {
  proposer, proposalFields, verifyProposal, voteFields, verifyCertificate,
  ResearchVoteLock, TRUSTED_MODE
} = require("./engine.cjs");
const crypto = require("node:crypto");

const HEX = /^0x[0-9a-f]{64}$/;
const PHASES = Object.freeze(["propose", "prevote", "precommit", "commit"]);

function must(ok, why) { if (!ok) throw Error(why); }
function safeHeight(h) {
  must(Number.isSafeInteger(h) && h >= 1, "Invalid height");
}
function safeRound(r) {
  must(Number.isSafeInteger(r) && r >= 0, "Invalid round");
}

function phaseTimeoutMs(baseMs, phase, round) {
  must(Number.isSafeInteger(baseMs) && baseMs >= 10 && baseMs <= 60_000,
    "base timeout must be 10..60000 ms");
  const phaseIndex = PHASES.indexOf(phase);
  must(phaseIndex >= 0, "Unknown phase");
  safeRound(round);
  // Linear backoff by round; slight phase stretch so precommit outlasts prevote.
  return baseMs * (1 + round) * (1 + Math.floor(phaseIndex / 2));
}

function voteTag(phase) {
  if (phase === "prevote") return "prevote";
  if (phase === "precommit") return "commit"; // domain tag aligned with engine commit certs
  throw Error("Votes only exist in prevote/precommit phases");
}

function signedMessage(tag, fields) {
  // Match engine PREFIX/tag encoding by reusing engine.signedMessage if available.
  const engine = require("./engine.cjs");
  return engine.signedMessage(tag, fields);
}

/**
 * Collect phase votes for one proposal. Precommit uses engine.verifyCertificate
 * so a commit quorum is identical to the existing research certificate format.
 */
function tallyPhase(committee, proposal, votes, phase) {
  must(committee?.mode === TRUSTED_MODE, "Research mode required");
  if (phase === "precommit") {
    return verifyCertificate(committee, proposal, votes);
  }
  must(phase === "prevote", "Unsupported tally phase");
  const fields = verifyProposal(committee, proposal);
  must(Array.isArray(votes) && votes.length <= committee.validators.length,
    "Malformed prevote set");
  const seen = new Set();
  for (const vote of votes) {
    must(vote && typeof vote === "object", "Invalid prevote");
    const signer = committee.byId.get(vote.validatorId);
    must(!!signer, "Unadmitted prevote signer");
    must(!seen.has(vote.validatorId), "Duplicate prevote");
    const ok = crypto.verify(
      null,
      signedMessage("prevote", [...fields, vote.validatorId]),
      signer.pub,
      Buffer.from(vote.signature, "base64"),
    );
    must(ok, "Forged or wrong-context prevote");
    seen.add(vote.validatorId);
  }
  must(seen.size >= committee.quorum, "Insufficient prevote quorum");
  return Object.freeze({
    valid: true,
    phase: "prevote",
    chainId: committee.chainId,
    height: proposal.height,
    round: proposal.round,
    blockHash: proposal.blockHash,
    signers: seen.size,
    quorum: committee.quorum,
    productionConsensus: false,
  });
}

/**
 * Height-scoped research driver. Caller supplies time and network; this only
 * tracks phase, round, locks, and certificate acceptance rules.
 */
class ResearchRoundMachine {
  constructor(committee, { baseTimeoutMs = 200, height = 1, voteLock = null } = {}) {
    must(committee?.mode === TRUSTED_MODE, "Research committee required");
    safeHeight(height);
    this.committee = committee;
    this.baseTimeoutMs = baseTimeoutMs;
    this.height = height;
    this.round = 0;
    this.phase = "propose";
    this.activeProposal = null;
    this.lockedBlockHash = null;
    this.lockedRound = null;
    this.decision = null;
    this.voteLock = voteLock || new ResearchVoteLock();
    this.history = [];
  }

  expectedProposer() {
    return proposer(this.committee, this.height, this.round);
  }

  timeoutMs() {
    return phaseTimeoutMs(this.baseTimeoutMs, this.phase, this.round);
  }

  snapshot() {
    return Object.freeze({
      height: this.height,
      round: this.round,
      phase: this.phase,
      lockedBlockHash: this.lockedBlockHash,
      lockedRound: this.lockedRound,
      decision: this.decision,
      expectedProposer: this.expectedProposer(),
      timeoutMs: this.timeoutMs(),
      productionConsensus: false,
    });
  }

  _record(event, detail) {
    this.history.push(Object.freeze({ event, detail, ...this.snapshot() }));
  }

  /**
   * Accept a signed proposal for the current height/round in propose phase.
   * If a lock exists, the proposal must match the locked block hash.
   */
  onProposal(proposal) {
    must(!this.decision, "Height already decided");
    must(this.phase === "propose", "Not in propose phase");
    must(proposal && proposal.height === this.height && proposal.round === this.round,
      "Proposal height/round mismatch");
    verifyProposal(this.committee, proposal);
    if (this.lockedBlockHash !== null) {
      must(proposal.blockHash === this.lockedBlockHash,
        "Proposal conflicts with locked block");
    }
    this.activeProposal = Object.freeze({ ...proposal });
    this.phase = "prevote";
    this._record("proposal_accepted", { blockHash: proposal.blockHash });
    return this.snapshot();
  }

  /**
   * Apply a prevote quorum for the active proposal.
   */
  onPrevoteQuorum(proposal, votes) {
    must(!this.decision, "Height already decided");
    must(this.phase === "prevote", "Not in prevote phase");
    must(proposal.height === this.height && proposal.round === this.round,
      "Prevote proposal context mismatch");
    must(this.activeProposal && proposal.blockHash === this.activeProposal.blockHash &&
      proposal.previousBlockHash === this.activeProposal.previousBlockHash,
      "Prevote quorum conflicts with accepted proposal");
    const proof = tallyPhase(this.committee, proposal, votes, "prevote");
    if (this.lockedBlockHash !== null) {
      must(proposal.blockHash === this.lockedBlockHash,
        "Prevote quorum conflicts with lock");
    }
    this.phase = "precommit";
    this._record("prevote_quorum", { signers: proof.signers, blockHash: proposal.blockHash });
    return { proof, state: this.snapshot() };
  }

  /**
   * Apply a precommit (commit-tag) quorum. Locks the block and decides the height.
   */
  onPrecommitQuorum(proposal, votes) {
    must(!this.decision, "Height already decided");
    must(this.phase === "precommit", "Not in precommit phase");
    must(proposal.height === this.height && proposal.round === this.round,
      "Precommit proposal context mismatch");
    must(this.activeProposal && proposal.blockHash === this.activeProposal.blockHash &&
      proposal.previousBlockHash === this.activeProposal.previousBlockHash,
      "Precommit quorum conflicts with accepted proposal");
    const proof = tallyPhase(this.committee, proposal, votes, "precommit");
    // Research lock: no conflicting block at this height for any local voter model.
    for (const vote of votes) {
      this.voteLock.accept(
        this.committee.epoch,
        this.height,
        this.round,
        vote.validatorId,
        proposal.blockHash,
      );
    }
    this.lockedBlockHash = proposal.blockHash;
    this.lockedRound = this.round;
    this.phase = "commit";
    this.decision = Object.freeze({
      height: this.height,
      round: this.round,
      blockHash: proposal.blockHash,
      signers: proof.signers,
      quorum: proof.quorum,
      productionConsensus: false,
      researchOnly: true,
    });
    this._record("decided", this.decision);
    return { proof, decision: this.decision, state: this.snapshot() };
  }

  /**
   * Caller-driven timeout: advance round, return to propose. Lock is retained.
   */
  onTimeout() {
    must(!this.decision, "Height already decided");
    const from = { phase: this.phase, round: this.round };
    this.round += 1;
    this.phase = "propose";
    this.activeProposal = null;
    this._record("timeout_view_change", from);
    return this.snapshot();
  }

  /**
   * Move to the next height after a decision. Clears lock for the new height.
   */
  advanceHeight() {
    must(this.decision, "Cannot advance without a decision");
    this.height += 1;
    this.round = 0;
    this.phase = "propose";
    this.activeProposal = null;
    this.lockedBlockHash = null;
    this.lockedRound = null;
    this.decision = null;
    this._record("height_advanced", { height: this.height });
    return this.snapshot();
  }
}

function signPhaseVote(privateKey, committee, proposal, phase) {
  must(phase === "prevote" || phase === "precommit", "Invalid vote phase");
  const fields = verifyProposal(committee, proposal);
  const der = crypto.createPublicKey(privateKey).export({ type: "spki", format: "der" });
  const engine = require("./engine.cjs");
  const validatorId = engine.hash(der);
  must(committee.byId.has(validatorId), "Key not in committee");
  const tag = voteTag(phase);
  const payload = tag === "prevote"
    ? signedMessage("prevote", [...fields, validatorId])
    : signedMessage("commit", voteFields(fields, validatorId));
  return {
    validatorId,
    signature: crypto.sign(null, payload, privateKey).toString("base64"),
    researchOnly: true,
  };
}

module.exports = {
  PHASES,
  phaseTimeoutMs,
  tallyPhase,
  ResearchRoundMachine,
  signPhaseVote,
};
