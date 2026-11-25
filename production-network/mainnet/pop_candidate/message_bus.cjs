"use strict";
/*
 * Research-only in-process message bus for PoP round-machine experiments.
 *
 * NOT a production P2P stack, NOT gossip, NOT authenticated transport,
 * NOT mainnet networking. Used to drive ResearchRoundMachine peers in tests.
 */
const { EventEmitter } = require("node:events");

const TYPES = Object.freeze(["proposal", "prevote", "precommit", "timeout"]);

function must(ok, why) { if (!ok) throw Error(why); }

/**
 * Envelope shape (research):
 * {
 *   type: "proposal"|"prevote"|"precommit"|"timeout",
 *   from: validatorId (0x…64),
 *   height, round,
 *   chainId,
 *   payload: object,   // proposal body or vote {validatorId,signature}
 *   researchOnly: true
 * }
 */
class ResearchMessageBus extends EventEmitter {
  constructor({ latencyMs = 0, dropRate = 0, rng = Math.random } = {}) {
    super();
    must(Number.isFinite(latencyMs) && latencyMs >= 0 && latencyMs <= 5000,
      "latencyMs must be 0..5000");
    must(Number.isFinite(dropRate) && dropRate >= 0 && dropRate <= 1,
      "dropRate must be 0..1");
    this.latencyMs = latencyMs;
    this.dropRate = dropRate;
    this.rng = rng;
    this.partitioned = new Set(); // validatorIds that cannot send or receive
    this.delivered = [];
    this.dropped = [];
    this._seq = 0;
  }

  /** Isolate a set of validator IDs (no send/receive). */
  setPartition(validatorIds) {
    this.partitioned = new Set(validatorIds || []);
  }

  clearPartition() {
    this.partitioned = new Set();
  }

  publish(envelope) {
    must(envelope && typeof envelope === "object", "envelope required");
    must(TYPES.includes(envelope.type), "unknown message type");
    must(typeof envelope.from === "string" && /^0x[0-9a-f]{64}$/.test(envelope.from),
      "from must be validator id");
    must(Number.isSafeInteger(envelope.height) && envelope.height >= 1, "invalid height");
    must(Number.isSafeInteger(envelope.round) && envelope.round >= 0, "invalid round");
    must(typeof envelope.chainId === "string", "chainId required");
    const msg = Object.freeze({
      ...envelope,
      seq: ++this._seq,
      researchOnly: true,
      productionConsensus: false,
    });
    if (this.partitioned.has(msg.from)) {
      this.dropped.push({ reason: "partition_sender", msg });
      return false;
    }
    if (this.rng() < this.dropRate) {
      this.dropped.push({ reason: "drop_rate", msg });
      return false;
    }
    const deliver = () => {
      // Receivers in partition do not get the message.
      this.delivered.push(msg);
      this.emit("message", msg);
      this.emit(msg.type, msg);
    };
    if (this.latencyMs > 0) {
      setTimeout(deliver, this.latencyMs);
    } else {
      // Async microtask so publish() returns before handlers run (avoids reentrancy).
      queueMicrotask(deliver);
    }
    return true;
  }

  /**
   * Subscribe to all messages. Handler may filter by type.
   * Returns unsubscribe function.
   */
  subscribe(handler) {
    must(typeof handler === "function", "handler required");
    const wrapped = (msg) => {
      // Partitioned nodes still "hear" nothing: filter at delivery for receivers
      // is applied by the peer driver (bus delivers to all subscribers; peer
      // ignores if it is partitioned). Keep bus simple.
      handler(msg);
    };
    this.on("message", wrapped);
    return () => this.off("message", wrapped);
  }

  stats() {
    return {
      delivered: this.delivered.length,
      dropped: this.dropped.length,
      seq: this._seq,
      partitioned: [...this.partitioned],
      researchOnly: true,
    };
  }
}

module.exports = { ResearchMessageBus, TYPES };
