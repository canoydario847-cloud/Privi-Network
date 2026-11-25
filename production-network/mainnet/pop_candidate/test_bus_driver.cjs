"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const {
  hash, signedMessage, parseRegistry, positionStamp, TRUSTED_MODE,
} = require("./engine.cjs");
const { ResearchMessageBus } = require("./message_bus.cjs");
const { runResearchHeight, ResearchBusPeer, validatorIdFromKey } = require("./bus_driver.cjs");

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
  const chainId = "privi-pop-research-bus-v1", genesisHash = "0x" + "a".repeat(64);
  const epoch = 1;
  const registry = {
    mode: TRUSTED_MODE, chainId, genesisHash, epoch,
    validators: keys.map((k, i) => {
      const operatorId = "OPERATOR_" + i;
      const faultDomain = "host" + i + ".bus.test";
      const companyId = "ORG_" + i, positionSequence = i + 1;
      const anchorBlockHash = hash(Buffer.from("bus-pos-" + i));
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
  return { committee, keysById, keys };
}

test("bus delivers proposal envelopes asynchronously", async () => {
  const bus = new ResearchMessageBus();
  const seen = [];
  bus.subscribe((m) => seen.push(m.type));
  bus.publish({
    type: "proposal",
    from: "0x" + "1".repeat(64),
    height: 1,
    round: 0,
    chainId: "privi-pop-research-bus-v1",
    payload: {},
  });
  await new Promise((r) => queueMicrotask(r));
  assert.deepEqual(seen, ["proposal"]);
  assert.equal(bus.stats().researchOnly, true);
});

test("four peers reach research decision over the bus", async () => {
  const f = fixture(4);
  const blockHash = "0x" + "d".repeat(64);
  const run = runResearchHeight({
    committee: f.committee,
    keysById: f.keysById,
    height: 1,
    blockHash,
    baseTimeoutMs: 200,
    wallMs: 3000,
  });
  const result = await run.waitForDecision(3);
  assert.ok(result.decisions.length >= 3);
  for (const d of result.decisions) {
    assert.equal(d.blockHash, blockHash);
    assert.equal(d.productionConsensus, false);
    assert.equal(d.researchOnly, true);
  }
  assert.equal(result.productionConsensus, false);
  assert.ok(result.bus.delivered >= 1);
});

test("partitioned peer does not decide while majority does", async () => {
  const f = fixture(4);
  const bus = new ResearchMessageBus();
  const isolated = f.committee.validators[3].id;
  bus.setPartition([isolated]);
  const peers = f.committee.validators.map((v) => {
    const peer = new ResearchBusPeer({
      committee: f.committee,
      privateKey: f.keysById.get(v.id),
      bus,
      height: 1,
      baseTimeoutMs: 300,
      blockHashForPropose: "0x" + "e".repeat(64),
    });
    return peer;
  });
  for (const p of peers) p.start();
  await new Promise((r) => setTimeout(r, 800));
  const decided = peers.filter((p) => p.machine.decision);
  const isolatedPeer = peers.find((p) => p.validatorId === isolated);
  assert.ok(decided.length >= 3, "majority should decide");
  assert.equal(isolatedPeer.machine.decision, null);
  for (const p of peers) p.stop();
});

test("validatorIdFromKey matches committee id", () => {
  const f = fixture(4);
  for (const k of f.keys) {
    assert.equal(validatorIdFromKey(k.privateKey), k.id);
  }
});
