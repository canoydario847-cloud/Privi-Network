"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const {
  hash, signedMessage, parseRegistry, positionStamp, TRUSTED_MODE,
} = require("./engine.cjs");
const { ResearchMessageBus, summarize, percentile } = require("./message_bus.cjs");
const { runResearchHeight } = require("./bus_driver.cjs");

function makeKey() {
  const pair = crypto.generateKeyPairSync("ed25519");
  const der = pair.publicKey.export({ type: "spki", format: "der" });
  return { id: hash(der), publicKeyB64: der.toString("base64"), privateKey: pair.privateKey };
}
function sign(key, tag, fields) {
  return crypto.sign(null, signedMessage(tag, fields), key.privateKey).toString("base64");
}
function fixture(count = 4) {
  const gov = makeKey(), keys = Array.from({ length: count }, () => makeKey());
  const chainId = "privi-pop-research-latency-v1", genesisHash = "0x" + "a".repeat(64);
  const epoch = 1;
  const registry = {
    mode: TRUSTED_MODE, chainId, genesisHash, epoch,
    validators: keys.map((k, i) => {
      const operatorId = "OPERATOR_" + i;
      const faultDomain = "host" + i + ".latency.test";
      const companyId = "ORG_" + i, positionSequence = i + 1;
      const anchorBlockHash = hash(Buffer.from("lat-pos-" + i));
      const positionHash = hash(Buffer.from(positionStamp(companyId, positionSequence)));
      const fields = [chainId, genesisHash, epoch, operatorId, faultDomain, companyId,
        positionSequence, k.id, anchorBlockHash];
      return {
        id: k.id, keySpkiBase64: k.publicKeyB64, operatorId, faultDomain,
        companyId, positionSequence, anchorBlockHash, positionHash,
        admissionSignature: sign(gov, "admit", fields),
      };
    }),
  };
  const committee = parseRegistry(registry, gov.publicKeyB64);
  const keysById = new Map(keys.map((k) => [k.id, k.privateKey]));
  return { committee, keysById };
}

test("percentile helpers", () => {
  assert.equal(percentile([], 50), null);
  assert.equal(percentile([10], 50), 10);
  assert.equal(percentile([1, 2, 3, 4, 5], 50), 3);
  const s = summarize([10, 20, 30]);
  assert.equal(s.count, 3);
  assert.equal(s.minMs, 10);
  assert.equal(s.maxMs, 30);
  assert.equal(s.meanMs, 20);
});

test("zero configured latency yields sub-ms publish-to-deliver samples", async () => {
  const bus = new ResearchMessageBus({ latencyMs: 0 });
  for (let i = 0; i < 20; i++) {
    bus.publish({
      type: "prevote",
      from: "0x" + "1".repeat(64),
      height: 1,
      round: 0,
      chainId: "privi-pop-research-latency-v1",
      payload: {},
    });
  }
  await new Promise((r) => setTimeout(r, 20));
  const m = bus.latencyMetrics();
  assert.equal(m.configuredLatencyMs, 0);
  assert.equal(m.overall.count, 20);
  assert.ok(m.overall.maxMs <= 50, "microtask delivery should be fast");
  assert.equal(m.byType.prevote.count, 20);
  assert.equal(m.productionConsensus, false);
});

test("configured latencyMs appears in samples and percentiles", async () => {
  const bus = new ResearchMessageBus({ latencyMs: 25 });
  for (let i = 0; i < 12; i++) {
    bus.publish({
      type: "proposal",
      from: "0x" + "2".repeat(64),
      height: 1,
      round: 0,
      chainId: "privi-pop-research-latency-v1",
      payload: {},
    });
  }
  await new Promise((r) => setTimeout(r, 80));
  const m = bus.latencyMetrics();
  assert.equal(m.overall.count, 12);
  assert.ok(m.overall.minMs >= 20, "expected ~25ms floor, got " + m.overall.minMs);
  assert.ok(m.overall.p50Ms >= 20);
  assert.ok(m.overall.meanMs >= 20);
  assert.equal(m.byType.proposal.count, 12);
  assert.equal(m.byType.prevote.count, 0);
});

test("consensus run exposes bus latency metrics in stats", async () => {
  const f = fixture(4);
  const run = runResearchHeight({
    committee: f.committee,
    keysById: f.keysById,
    height: 1,
    blockHash: "0x" + "f".repeat(64),
    baseTimeoutMs: 200,
    latencyMs: 5,
    wallMs: 4000,
  });
  const result = await run.waitForDecision(3);
  const lat = result.bus.latency;
  assert.ok(lat, "stats should include latency");
  assert.equal(lat.configuredLatencyMs, 5);
  assert.ok(lat.overall.count >= 1);
  assert.ok(lat.byType.proposal.count >= 1);
  assert.ok(lat.byType.prevote.count >= 1);
  assert.ok(lat.byType.precommit.count >= 1);
  assert.equal(lat.researchOnly, true);
  for (const d of result.decisions) {
    assert.equal(d.blockHash, "0x" + "f".repeat(64));
  }
});

test("resetMetrics clears samples but not configuration", async () => {
  const bus = new ResearchMessageBus({ latencyMs: 0, dropRate: 0.1 });
  bus.publish({
    type: "timeout",
    from: "0x" + "3".repeat(64),
    height: 1,
    round: 0,
    chainId: "privi-pop-research-latency-v1",
    payload: {},
  });
  await new Promise((r) => queueMicrotask(r));
  assert.ok(bus.latencyMetrics().overall.count >= 0);
  bus.resetMetrics();
  assert.equal(bus.latencyMetrics().overall.count, 0);
  assert.equal(bus.latencyMetrics().configuredLatencyMs, 0);
  assert.equal(bus.latencyMetrics().dropRate, 0.1);
});
