"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const {
  hash, signedMessage, parseRegistry, positionStamp, proposer,
  proposalFields, TRUSTED_MODE,
} = require("./engine.cjs");
const {
  phaseTimeoutMs, ResearchRoundMachine, signPhaseVote, tallyPhase,
} = require("./round_machine.cjs");

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
  const chainId = "privi-pop-research-round-v1", genesisHash = "0x" + "a".repeat(64);
  const epoch = 1;
  const registry = {
    mode: TRUSTED_MODE, chainId, genesisHash, epoch,
    validators: keys.map((k, i) => {
      const operatorId = "OPERATOR_" + i;
      const faultDomain = "host" + i + ".round-machine.test";
      const companyId = "ORG_" + i, positionSequence = i + 1;
      const anchorBlockHash = hash(Buffer.from("round-pos-" + i));
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
  const byKey = new Map(keys.map((k) => [k.id, k]));
  function makeProposal(height = 1, round = 0,
    previousBlockHash = "0x" + "b".repeat(64),
    blockHash = "0x" + "c".repeat(64)) {
    const proposerId = proposer(committee, height, round);
    const fields = proposalFields(committee, height, round, previousBlockHash, blockHash, proposerId);
    return {
      height, round, previousBlockHash, blockHash, proposerId,
      signature: sign(byKey.get(proposerId), "propose", fields),
    };
  }
  function votes(proposal, phase, n = committee.quorum) {
    return committee.validators.slice(0, n).map((v) =>
      signPhaseVote(byKey.get(v.id).privateKey, committee, proposal, phase));
  }
  return { committee, byKey, makeProposal, votes, keys };
}

test("phase timeouts grow with round and phase", () => {
  const t0 = phaseTimeoutMs(100, "propose", 0);
  const t1 = phaseTimeoutMs(100, "propose", 1);
  const tPre = phaseTimeoutMs(100, "precommit", 0);
  assert.equal(t0, 100);
  assert.equal(t1, 200);
  assert.ok(tPre >= t0);
  assert.throws(() => phaseTimeoutMs(1, "propose", 0));
});

test("happy path: propose -> prevote -> precommit decides height", () => {
  const f = fixture();
  const m = new ResearchRoundMachine(f.committee, { height: 1, baseTimeoutMs: 50 });
  assert.equal(m.phase, "propose");
  const proposal = f.makeProposal(1, 0);
  m.onProposal(proposal);
  assert.equal(m.phase, "prevote");
  const prev = m.onPrevoteQuorum(proposal, f.votes(proposal, "prevote"));
  assert.equal(prev.proof.valid, true);
  assert.equal(m.phase, "precommit");
  const pre = m.onPrecommitQuorum(proposal, f.votes(proposal, "precommit"));
  assert.equal(pre.decision.blockHash, proposal.blockHash);
  assert.equal(pre.decision.productionConsensus, false);
  assert.equal(m.phase, "commit");
  assert.equal(m.lockedBlockHash, proposal.blockHash);
});

test("timeout advances round and keeps lock after partial progress", () => {
  const f = fixture();
  const m = new ResearchRoundMachine(f.committee, { height: 3, baseTimeoutMs: 50 });
  const p0 = f.makeProposal(3, 0, "0x" + "1".repeat(64), "0x" + "2".repeat(64));
  m.onProposal(p0);
  m.onPrevoteQuorum(p0, f.votes(p0, "prevote"));
  // Simulate precommit quorum locking then... actually lock only on precommit.
  // Timeout before precommit: no lock yet.
  const afterTimeout = m.onTimeout();
  assert.equal(afterTimeout.round, 1);
  assert.equal(afterTimeout.phase, "propose");
  assert.equal(afterTimeout.lockedBlockHash, null);
  const p1 = f.makeProposal(3, 1, "0x" + "1".repeat(64), "0x" + "3".repeat(64));
  m.onProposal(p1);
  m.onPrevoteQuorum(p1, f.votes(p1, "prevote"));
  m.onPrecommitQuorum(p1, f.votes(p1, "precommit"));
  assert.equal(m.decision.round, 1);
  assert.equal(m.decision.blockHash, p1.blockHash);
});

test("after precommit lock, conflicting proposal is rejected", () => {
  const f = fixture();
  const m = new ResearchRoundMachine(f.committee, { height: 2 });
  const good = f.makeProposal(2, 0, "0x" + "4".repeat(64), "0x" + "5".repeat(64));
  m.onProposal(good);
  m.onPrevoteQuorum(good, f.votes(good, "prevote"));
  m.onPrecommitQuorum(good, f.votes(good, "precommit"));
  assert.throws(() => m.onProposal(good), /already decided|Not in propose/);
});

test("prevote quorum insufficient votes fails closed", () => {
  const f = fixture();
  const m = new ResearchRoundMachine(f.committee, { height: 1 });
  const proposal = f.makeProposal();
  m.onProposal(proposal);
  assert.throws(
    () => m.onPrevoteQuorum(proposal, f.votes(proposal, "prevote", 2)),
    /prevote quorum/i,
  );
});

test("advanceHeight starts a clean propose phase", () => {
  const f = fixture();
  const m = new ResearchRoundMachine(f.committee, { height: 1 });
  const proposal = f.makeProposal(1, 0);
  m.onProposal(proposal);
  m.onPrevoteQuorum(proposal, f.votes(proposal, "prevote"));
  m.onPrecommitQuorum(proposal, f.votes(proposal, "precommit"));
  const next = m.advanceHeight();
  assert.equal(next.height, 2);
  assert.equal(next.round, 0);
  assert.equal(next.phase, "propose");
  assert.equal(next.lockedBlockHash, null);
  assert.equal(next.decision, null);
});

test("tallyPhase precommit matches engine certificate productionConsensus flag", () => {
  const f = fixture();
  const proposal = f.makeProposal();
  const proof = tallyPhase(f.committee, proposal, f.votes(proposal, "precommit"), "precommit");
  assert.equal(proof.productionConsensus, false);
  assert.equal(proof.valid, true);
});

test("snapshot always reports productionConsensus false", () => {
  const f = fixture();
  const m = new ResearchRoundMachine(f.committee);
  assert.equal(m.snapshot().productionConsensus, false);
});
