"use strict";
// Research-only POP vote domain separation; not a production signature verifier.
const test = require("node:test");
const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");

function voteDigest(vote) {
  const fields = ["chainId", "epoch", "height", "round", "phase", "blockHash"];
  if (!vote || typeof vote !== "object" || Array.isArray(vote)) throw Error("invalid vote");
  for (const field of fields) {
    if (typeof vote[field] !== "string" || !vote[field].length || vote[field].trim() !== vote[field]) {
      throw Error(`invalid ${field}`);
    }
  }
  if (!/^(0|[1-9][0-9]*)$/.test(vote.epoch) || !/^(0|[1-9][0-9]*)$/.test(vote.height) || !/^(0|[1-9][0-9]*)$/.test(vote.round)) throw Error("noncanonical integer");
  if (!/^[a-f0-9]{64}$/.test(vote.blockHash)) throw Error("invalid block hash");
  if (!["prevote", "precommit"].includes(vote.phase)) throw Error("invalid phase");
  const payload = JSON.stringify(["PRVI-POP-VOTE-RESEARCH-v1", ...fields.map(k => vote[k])]);
  return createHash("sha256").update(payload).digest("hex");
}

test("candidate vote digest binds chain, epoch, height, round, phase and block", () => {
  const v = { chainId: "privi-native-mainnet", epoch: "7", height: "42", round: "0", phase: "prevote", blockHash: "a".repeat(64) };
  const baseline = voteDigest(v);
  for (const [field, value] of Object.entries({ chainId: "privi-valueless-test", epoch: "8", height: "43", round: "1", phase: "precommit", blockHash: "b".repeat(64) })) {
    assert.notEqual(voteDigest({ ...v, [field]: value }), baseline, `${field} must bind`);
  }
  assert.equal(voteDigest({ ...v }), baseline);
});

test("candidate vote digest rejects ambiguous encodings", () => {
  const v = { chainId: "privi-native-mainnet", epoch: "7", height: "42", round: "0", phase: "prevote", blockHash: "a".repeat(64) };
  for (const change of [{ epoch: "07" }, { height: "4.2" }, { round: "-1" }, { phase: "commit" }, { chainId: " privi-native-mainnet" }, { blockHash: "A".repeat(64) }]) {
    assert.throws(() => voteDigest({ ...v, ...change }));
  }
});
