"use strict";
/*
 * Multi-worker research bus host for PoP round-machine experiments.
 * RESEARCH ONLY — worker_threads relay, not production P2P or mainnet.
 */
const { Worker } = require("node:worker_threads");
const path = require("node:path");
const crypto = require("node:crypto");
const { ResearchMessageBus } = require("./message_bus.cjs");

function must(ok, why) { if (!ok) throw Error(why); }

/**
 * Host process: N worker peers + central ResearchMessageBus relay.
 * Optional latency/drop applied on the host bus before fan-out.
 */
class ResearchWorkerBusHost {
  constructor({
    committee,
    keysById,
    height = 1,
    baseTimeoutMs = 80,
    blockHash,
    previousBlockHash,
    latencyMs = 0,
    dropRate = 0,
    governanceKeySpkiB64,
    committeeRegistry,
  }) {
    must(committee && keysById, "committee and keys required");
    must(typeof governanceKeySpkiB64 === "string", "governance key required");
    must(committeeRegistry && typeof committeeRegistry === "object", "registry required");
    this.committee = committee;
    this.bus = new ResearchMessageBus({ latencyMs, dropRate });
    this.workers = [];
    this.decisions = new Map();
    this.ready = new Set();
    this._unsub = null;
    this.height = height;
    this.baseTimeoutMs = baseTimeoutMs;
    this.blockHash = blockHash || ("0x" + "c".repeat(64));
    this.previousBlockHash = previousBlockHash || ("0x" + "b".repeat(64));
    this.governanceKeySpkiB64 = governanceKeySpkiB64;
    this.committeeRegistry = committeeRegistry;
    this.keysById = keysById;
  }

  start() {
    const boot = path.join(__dirname, "worker_peer_boot.cjs");
    this._unsub = this.bus.subscribe((envelope) => {
      for (const w of this.workers) {
        w.postMessage({ kind: "envelope", envelope });
      }
    });
    for (const v of this.committee.validators) {
      const privateKey = this.keysById.get(v.id);
      must(privateKey, "missing key " + v.id);
      const pkcs8 = privateKey.export({ type: "pkcs8", format: "der" }).toString("base64");
      const worker = new Worker(boot, {
        workerData: {
          committeeRegistry: this.committeeRegistry,
          governanceKeySpkiB64: this.governanceKeySpkiB64,
          privateKeyPkcs8B64: pkcs8,
          height: this.height,
          baseTimeoutMs: this.baseTimeoutMs,
          previousBlockHash: this.previousBlockHash,
          blockHashForPropose: this.blockHash,
          validatorId: v.id,
        },
      });
      worker.on("message", (m) => this._onWorkerMessage(worker, m));
      worker.on("error", (err) => {
        this.decisions.set(v.id, { error: String(err.message || err) });
      });
      this.workers.push(worker);
    }
    return this;
  }

  _onWorkerMessage(_worker, m) {
    if (!m || typeof m !== "object") return;
    if (m.kind === "ready") {
      this.ready.add(m.validatorId);
    } else if (m.kind === "publish") {
      this.bus.publish(m.envelope);
    } else if (m.kind === "decided") {
      this.decisions.set(m.validatorId, m.decision);
    }
  }

  waitForDecision(minPeers = this.committee.quorum, wallMs = 5000) {
    return new Promise((resolve, reject) => {
      const start = Date.now();
      const tick = () => {
        if (this.decisions.size >= minPeers) {
          this.stop();
          resolve({
            decisions: [...this.decisions.values()].filter((d) => d && d.blockHash),
            bus: this.bus.stats(),
            workers: this.workers.length,
            productionConsensus: false,
            researchOnly: true,
          });
          return;
        }
        if (Date.now() - start > wallMs) {
          this.stop();
          reject(new Error(
            "worker research height timed out; decided=" + this.decisions.size,
          ));
          return;
        }
        setTimeout(tick, 10);
      };
      tick();
    });
  }

  async stop() {
    if (this._unsub) this._unsub();
    this._unsub = null;
    await Promise.all(this.workers.map((w) => new Promise((resolve) => {
      const t = setTimeout(() => { w.terminate().finally(resolve); }, 500);
      w.once("exit", () => { clearTimeout(t); resolve(); });
      try { w.postMessage({ kind: "stop" }); } catch { /* */ }
      w.terminate().catch(() => {}).finally(() => { clearTimeout(t); resolve(); });
    })));
    this.workers = [];
  }
}

module.exports = { ResearchWorkerBusHost };
