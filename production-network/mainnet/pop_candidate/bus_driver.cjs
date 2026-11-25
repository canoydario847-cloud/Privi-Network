"use strict";
/*
 * Wire ResearchRoundMachine peers to ResearchMessageBus.
 * RESEARCH ONLY — not production consensus, not PRVI, not mainnet.
 */
const crypto = require("node:crypto");
const {
  proposer, proposalFields, verifyProposal, TRUSTED_MODE,
} = require("./engine.cjs");
const {
  ResearchRoundMachine, signPhaseVote,
} = require("./round_machine.cjs");
const { ResearchMessageBus } = require("./message_bus.cjs");

function must(ok, why) { if (!ok) throw Error(why); }

function validatorIdFromKey(privateKey) {
  const der = crypto.createPublicKey(privateKey).export({ type: "spki", format: "der" });
  const { hash } = require("./engine.cjs");
  return hash(der);
}

/**
 * One research peer: local round machine + bus I/O + vote buffers.
 */
class ResearchBusPeer {
  constructor({
    committee,
    privateKey,
    bus,
    height = 1,
    baseTimeoutMs = 50,
    previousBlockHash = "0x" + "b".repeat(64),
    blockHashForPropose = null,
  }) {
    must(committee?.mode === TRUSTED_MODE, "research committee required");
    must(privateKey?.asymmetricKeyType === "ed25519", "Ed25519 required");
    must(bus instanceof ResearchMessageBus, "ResearchMessageBus required");
    this.committee = committee;
    this.privateKey = privateKey;
    this.validatorId = validatorIdFromKey(privateKey);
    must(committee.byId.has(this.validatorId), "key not in committee");
    this.bus = bus;
    this.machine = new ResearchRoundMachine(committee, { height, baseTimeoutMs });
    this.previousBlockHash = previousBlockHash;
    this.blockHashForPropose = blockHashForPropose || ("0x" + "c".repeat(64));
    this.prevotes = new Map(); // validatorId -> vote
    this.precommits = new Map();
    this.activeProposal = null;
    this.decisions = [];
    this.errors = [];
    this._unsub = null;
    this._timer = null;
  }

  start() {
    this._unsub = this.bus.subscribe((msg) => this._onMessage(msg));
    this._armTimeout();
    this._maybePropose();
    return this;
  }

  stop() {
    if (this._unsub) this._unsub();
    this._unsub = null;
    if (this._timer) clearTimeout(this._timer);
    this._timer = null;
  }

  snapshot() {
    return {
      validatorId: this.validatorId,
      machine: this.machine.snapshot(),
      decisions: this.decisions.slice(),
      productionConsensus: false,
      researchOnly: true,
    };
  }

  _armTimeout() {
    if (this._timer) clearTimeout(this._timer);
    if (this.machine.decision) return;
    const ms = this.machine.timeoutMs();
    this._timer = setTimeout(() => {
      try {
        if (this.machine.decision) return;
        this.machine.onTimeout();
        this.prevotes.clear();
        this.precommits.clear();
        this.activeProposal = null;
        this.bus.publish({
          type: "timeout",
          from: this.validatorId,
          height: this.machine.height,
          round: this.machine.round,
          chainId: this.committee.chainId,
          payload: { note: "local_timeout" },
        });
        this._armTimeout();
        this._maybePropose();
      } catch (e) {
        this.errors.push(String(e.message || e));
      }
    }, ms);
  }

  _maybePropose() {
    if (this.machine.decision) return;
    if (this.machine.phase !== "propose") return;
    if (this.machine.expectedProposer() !== this.validatorId) return;
    const height = this.machine.height;
    const round = this.machine.round;
    const previousBlockHash = this.previousBlockHash;
    const blockHash = this.blockHashForPropose;
    const proposerId = this.validatorId;
    const fields = proposalFields(
      this.committee, height, round, previousBlockHash, blockHash, proposerId,
    );
    const { signedMessage } = require("./engine.cjs");
    const signature = crypto.sign(
      null,
      signedMessage("propose", fields),
      this.privateKey,
    ).toString("base64");
    const proposal = {
      height, round, previousBlockHash, blockHash, proposerId, signature,
    };
    this.bus.publish({
      type: "proposal",
      from: this.validatorId,
      height,
      round,
      chainId: this.committee.chainId,
      payload: proposal,
    });
  }

  _onMessage(msg) {
    try {
      if (msg.chainId !== this.committee.chainId) return;
      // If this peer is partitioned, ignore inbound (simulates isolation).
      if (this.bus.partitioned.has(this.validatorId)) return;
      if (msg.type === "proposal") this._handleProposal(msg);
      else if (msg.type === "prevote") this._handlePrevote(msg);
      else if (msg.type === "precommit") this._handlePrecommit(msg);
      // timeout messages are informational; local timer drives view-change
    } catch (e) {
      this.errors.push(String(e.message || e));
    }
  }

  _handleProposal(msg) {
    if (this.machine.decision) return;
    if (msg.height !== this.machine.height || msg.round !== this.machine.round) return;
    if (this.machine.phase !== "propose") return;
    const proposal = msg.payload;
    this.machine.onProposal(proposal);
    this.activeProposal = proposal;
    this.prevotes.clear();
    this.precommits.clear();
    const vote = signPhaseVote(this.privateKey, this.committee, proposal, "prevote");
    this.prevotes.set(vote.validatorId, vote);
    this.bus.publish({
      type: "prevote",
      from: this.validatorId,
      height: proposal.height,
      round: proposal.round,
      chainId: this.committee.chainId,
      payload: vote,
    });
    this._tryPrevoteQuorum();
    this._armTimeout();
  }

  _handlePrevote(msg) {
    if (this.machine.decision) return;
    if (!this.activeProposal) return;
    if (msg.height !== this.machine.height || msg.round !== this.machine.round) return;
    const vote = msg.payload;
    this.prevotes.set(vote.validatorId, vote);
    this._tryPrevoteQuorum();
  }

  _tryPrevoteQuorum() {
    if (this.machine.phase !== "prevote") return;
    if (this.prevotes.size < this.committee.quorum) return;
    const votes = [...this.prevotes.values()];
    try {
      this.machine.onPrevoteQuorum(this.activeProposal, votes);
    } catch {
      return; // wait for more / valid set
    }
    const pre = signPhaseVote(
      this.privateKey, this.committee, this.activeProposal, "precommit",
    );
    this.precommits.set(pre.validatorId, pre);
    this.bus.publish({
      type: "precommit",
      from: this.validatorId,
      height: this.activeProposal.height,
      round: this.activeProposal.round,
      chainId: this.committee.chainId,
      payload: pre,
    });
    this._tryPrecommitQuorum();
    this._armTimeout();
  }

  _handlePrecommit(msg) {
    if (this.machine.decision) return;
    if (!this.activeProposal) return;
    if (msg.height !== this.machine.height || msg.round !== this.machine.round) return;
    const vote = msg.payload;
    this.precommits.set(vote.validatorId, vote);
    this._tryPrecommitQuorum();
  }

  _tryPrecommitQuorum() {
    if (this.machine.phase !== "precommit") return;
    if (this.precommits.size < this.committee.quorum) return;
    const votes = [...this.precommits.values()];
    try {
      const result = this.machine.onPrecommitQuorum(this.activeProposal, votes);
      this.decisions.push(result.decision);
      if (this._timer) clearTimeout(this._timer);
      this._timer = null;
    } catch {
      // incomplete or invalid set
    }
  }
}

/**
 * Spin up N peers on one bus for a single height experiment.
 */
function runResearchHeight({
  committee,
  keysById,
  height = 1,
  blockHash,
  previousBlockHash,
  baseTimeoutMs = 80,
  latencyMs = 0,
  dropRate = 0,
  wallMs = 2000,
}) {
  const bus = new ResearchMessageBus({ latencyMs, dropRate });
  const peers = [];
  for (const v of committee.validators) {
    const privateKey = keysById.get(v.id);
    must(privateKey, "missing key for " + v.id);
    const peer = new ResearchBusPeer({
      committee,
      privateKey,
      bus,
      height,
      baseTimeoutMs,
      previousBlockHash: previousBlockHash || ("0x" + "b".repeat(64)),
      blockHashForPropose: blockHash || ("0x" + "c".repeat(64)),
    });
    peers.push(peer);
  }
  for (const p of peers) p.start();
  return {
    bus,
    peers,
    waitForDecision(minPeers = committee.quorum) {
      return new Promise((resolve, reject) => {
        const start = Date.now();
        const tick = () => {
          const done = peers.filter((p) => p.machine.decision);
          if (done.length >= minPeers) {
            for (const p of peers) p.stop();
            resolve({
              decisions: done.map((p) => p.machine.decision),
              bus: bus.stats(),
              productionConsensus: false,
              researchOnly: true,
            });
            return;
          }
          if (Date.now() - start > wallMs) {
            for (const p of peers) p.stop();
            reject(new Error(
              "research height timed out; decided=" + done.length +
              " errors=" + JSON.stringify(peers.flatMap((p) => p.errors)),
            ));
            return;
          }
          setTimeout(tick, 5);
        };
        tick();
      });
    },
  };
}

module.exports = {
  ResearchBusPeer,
  runResearchHeight,
  validatorIdFromKey,
};
