#!/usr/bin/env node
/**
 * Research helper: print message-bus latency metrics for a few configured delays.
 * NOT production telemetry. NOT mainnet evidence.
 *
 *   node explore_latency.mjs
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const crypto = require("node:crypto");
const {
  hash, signedMessage, parseRegistry, positionStamp, TRUSTED_MODE,
} = require("./engine.cjs");
const { runResearchHeight } = require("./bus_driver.cjs");

function makeKey() {
  const pair = crypto.generateKeyPairSync("ed25519");
  const der = pair.publicKey.export({ type: "spki", format: "der" });
  return { id: hash(der), publicKeyB64: der.toString("base64"), privateKey: pair.privateKey };
}
function sign(key, tag, fields) {
  return crypto.sign(null, signedMessage(tag, fields), key.privateKey).toString("base64");
}
function fixture() {
  const gov = makeKey(), keys = Array.from({ length: 4 }, () => makeKey());
  const chainId = "privi-pop-research-explore-v1", genesisHash = "0x" + "a".repeat(64);
  const epoch = 1;
  const registry = {
    mode: TRUSTED_MODE, chainId, genesisHash, epoch,
    validators: keys.map((k, i) => {
      const operatorId = "OPERATOR_" + i;
      const faultDomain = "host" + i + ".explore.test";
      const companyId = "ORG_" + i, positionSequence = i + 1;
      const anchorBlockHash = hash(Buffer.from("ex-pos-" + i));
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
  return {
    committee: parseRegistry(registry, gov.publicKeyB64),
    keysById: new Map(keys.map((k) => [k.id, k.privateKey])),
  };
}

function fmt(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return (Math.round(n * 100) / 100).toFixed(2);
}

async function runOnce(latencyMs) {
  const f = fixture();
  const t0 = Date.now();
  const run = runResearchHeight({
    committee: f.committee,
    keysById: f.keysById,
    height: 1,
    blockHash: "0x" + "ab".repeat(32),
    baseTimeoutMs: 250,
    latencyMs,
    wallMs: 5000,
  });
  const result = await run.waitForDecision(3);
  const e2eMs = Date.now() - t0;
  const lat = result.bus.latency;
  return { latencyMs, e2eMs, lat, decided: result.decisions.length };
}

const rows = [];
for (const latencyMs of [0, 5, 15, 30]) {
  rows.push(await runOnce(latencyMs));
}

console.log("PoP research message-bus latency exploration");
console.log("(publish→deliver samples + wall-clock to ≥3 decisions)");
console.log("productionConsensus=false always\n");
console.log(
  "cfgMs".padStart(6),
  "e2eMs".padStart(8),
  "n".padStart(5),
  "mean".padStart(8),
  "p50".padStart(8),
  "p95".padStart(8),
  "max".padStart(8),
  "prop".padStart(5),
  "prev".padStart(5),
  "prec".padStart(5),
);
for (const r of rows) {
  const o = r.lat.overall;
  const b = r.lat.byType;
  console.log(
    String(r.latencyMs).padStart(6),
    String(r.e2eMs).padStart(8),
    String(o.count).padStart(5),
    fmt(o.meanMs).padStart(8),
    fmt(o.p50Ms).padStart(8),
    fmt(o.p95Ms).padStart(8),
    fmt(o.maxMs).padStart(8),
    String(b.proposal.count).padStart(5),
    String(b.prevote.count).padStart(5),
    String(b.precommit.count).padStart(5),
  );
}
console.log("\nNot production telemetry. Not mainnet evidence.");
