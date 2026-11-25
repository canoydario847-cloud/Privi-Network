"use strict";
/*
 * Research-only in-process message bus for PoP round-machine experiments.
 *
 * NOT a production P2P stack, NOT gossip, NOT authenticated transport,
 * NOT mainnet networking. Used to drive ResearchRoundMachine peers in tests.
 *
 * Latency metrics are research instrumentation only (publish→deliver delay).
 */
const { EventEmitter } = require("node:events");

const TYPES = Object.freeze(["proposal", "prevote", "precommit", "timeout"]);

function must(ok, why) { if (!ok) throw Error(why); }

function percentile(sorted, p) {
  if (!sorted.length) return null;
  if (sorted.length === 1) return sorted[0];
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  const w = idx - lo;
  return sorted[lo] * (1 - w) + sorted[hi] * w;
}

function summarize(samples) {
  if (!samples.length) {
    return {
      count: 0, minMs: null, maxMs: null, meanMs: null,
      p50Ms: null, p95Ms: null, p99Ms: null,
    };
  }
  const sorted = [...samples].sort((a, b) => a - b);
  const sum = sorted.reduce((a, b) => a + b, 0);
  return {
    count: sorted.length,
    minMs: sorted[0],
    maxMs: sorted[sorted.length - 1],
    meanMs: sum / sorted.length,
    p50Ms: percentile(sorted, 50),
    p95Ms: percentile(sorted, 95),
    p99Ms: percentile(sorted, 99),
  };
}

/**
 * Envelope shape (research):
 * {
 *   type: "proposal"|"prevote"|"precommit"|"timeout",
 *   from: validatorId (0x…64),
 *   height, round,
 *   chainId,
 *   payload: object,
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
    this.partitioned = new Set();
    this.delivered = [];
    this.dropped = [];
    this._seq = 0;
    /** @type {number[]} publish→deliver samples (ms) */
    this._latencySamples = [];
    /** @type {Record<string, number[]>} */
    this._latencyByType = Object.fromEntries(TYPES.map((t) => [t, []]));
  }

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
    const publishedAt = Date.now();
    const msg = Object.freeze({
      ...envelope,
      seq: ++this._seq,
      publishedAt,
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
      const deliveredAt = Date.now();
      const latencyMs = deliveredAt - publishedAt;
      this._latencySamples.push(latencyMs);
      this._latencyByType[msg.type].push(latencyMs);
      const withLatency = Object.freeze({ ...msg, deliveredAt, latencyMs });
      this.delivered.push(withLatency);
      this.emit("message", withLatency);
      this.emit(msg.type, withLatency);
    };
    if (this.latencyMs > 0) {
      setTimeout(deliver, this.latencyMs);
    } else {
      queueMicrotask(deliver);
    }
    return true;
  }

  subscribe(handler) {
    must(typeof handler === "function", "handler required");
    const wrapped = (msg) => { handler(msg); };
    this.on("message", wrapped);
    return () => this.off("message", wrapped);
  }

  /** Aggregate publish→deliver latency (research metrics only). */
  latencyMetrics() {
    const byType = {};
    for (const t of TYPES) {
      byType[t] = summarize(this._latencyByType[t]);
    }
    return {
      configuredLatencyMs: this.latencyMs,
      dropRate: this.dropRate,
      overall: summarize(this._latencySamples),
      byType,
      researchOnly: true,
      productionConsensus: false,
    };
  }

  resetMetrics() {
    this._latencySamples = [];
    this._latencyByType = Object.fromEntries(TYPES.map((t) => [t, []]));
    this.delivered = [];
    this.dropped = [];
  }

  stats() {
    return {
      delivered: this.delivered.length,
      dropped: this.dropped.length,
      seq: this._seq,
      partitioned: [...this.partitioned],
      latency: this.latencyMetrics(),
      researchOnly: true,
    };
  }
}

module.exports = { ResearchMessageBus, TYPES, summarize, percentile };
