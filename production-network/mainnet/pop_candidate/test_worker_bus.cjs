"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const {
  hash, signedMessage, parseRegistry, positionStamp, TRUSTED_MODE,
} = require("./engine.cjs");
const { ResearchWorkerBusHost } = require("./worker_bus.cjs");

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
  const chainId = "privi-pop-research-worker-v1", genesisHash = "0x" + "a".repeat(64);
  const epoch = 1;
  const registry = {
    mode: TRUSTED_MODE, chainId, genesisHash, epoch,
    validators: keys.map((k, i) => {
      const operatorId = "OPERATOR_" + i;
      const faultDomain = "host" + i + ".worker.test";
      const companyId = "ORG_" + i, positionSequence = i + 1;
      const anchorBlockHash = hash(Buffer.from("w-pos-" + i));
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
  return { committee, keysById, registry, gov };
}

test("four worker threads reach research decision via host bus", async () => {
  const f = fixture(4);
  const blockHash = "0x" + "cd".repeat(32);
  const host = new ResearchWorkerBusHost({
    committee: f.committee,
    keysById: f.keysById,
    governanceKeySpkiB64: f.gov.publicKeyB64,
    committeeRegistry: f.registry,
    height: 1,
    blockHash,
    baseTimeoutMs: 200,
    latencyMs: 2,
  });
  host.start();
  const result = await host.waitForDecision(3, 8000);
  assert.ok(result.decisions.length >= 3);
  for (const d of result.decisions) {
    assert.equal(d.blockHash, blockHash);
    assert.equal(d.productionConsensus, false);
  }
  assert.equal(result.productionConsensus, false);
  assert.equal(result.researchOnly, true);
  assert.equal(result.workers, 4);
  assert.ok(result.bus.delivered >= 1);
  if (result.bus.latency) {
    assert.equal(result.bus.latency.configuredLatencyMs, 2);
    assert.ok(result.bus.latency.overall.count >= 1);
  }
});

test("worker host with zero latency still decides", async () => {
  const f = fixture(4);
  const host = new ResearchWorkerBusHost({
    committee: f.committee,
    keysById: f.keysById,
    governanceKeySpkiB64: f.gov.publicKeyB64,
    committeeRegistry: f.registry,
    height: 1,
    blockHash: "0x" + "ef".repeat(32),
    baseTimeoutMs: 150,
    latencyMs: 0,
  });
  host.start();
  const result = await host.waitForDecision(3, 6000);
  assert.ok(result.decisions.length >= 3);
  assert.equal(result.researchOnly, true);
});
