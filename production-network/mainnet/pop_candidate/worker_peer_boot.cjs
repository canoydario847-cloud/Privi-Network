"use strict";
/*
 * Worker-thread entry for PoP research peers.
 * RESEARCH ONLY — not production networking or mainnet.
 */
const { parentPort, workerData } = require("node:worker_threads");
const crypto = require("node:crypto");
const {
  hash, signedMessage, parseRegistry, TRUSTED_MODE, proposalFields,
} = require("./engine.cjs");
const { ResearchRoundMachine, signPhaseVote } = require("./round_machine.cjs");

function must(ok, why) { if (!ok) throw Error(why); }

const {
  committeeRegistry,
  governanceKeySpkiB64,
  privateKeyPkcs8B64,
  height,
  baseTimeoutMs,
  previousBlockHash,
  blockHashForPropose,
  validatorId: expectedId,
} = workerData;

const privateKey = crypto.createPrivateKey({
  key: Buffer.from(privateKeyPkcs8B64, "base64"),
  format: "der",
  type: "pkcs8",
});
const committee = parseRegistry(committeeRegistry, governanceKeySpkiB64);
const der = crypto.createPublicKey(privateKey).export({ type: "spki", format: "der" });
const validatorId = hash(der);
must(validatorId === expectedId, "worker key mismatch");
must(committee.byId.has(validatorId), "worker not in committee");
must(committee.mode === TRUSTED_MODE, "research mode required");

const machine = new ResearchRoundMachine(committee, { height, baseTimeoutMs });
const prevotes = new Map();
const precommits = new Map();
let activeProposal = null;
let decision = null;
const errors = [];
let timer = null;

function publish(type, payload) {
  parentPort.postMessage({
    kind: "publish",
    envelope: {
      type,
      from: validatorId,
      height: payload.height ?? machine.height,
      round: payload.round ?? machine.round,
      chainId: committee.chainId,
      payload,
      researchOnly: true,
    },
  });
}

function armTimeout() {
  if (timer) clearTimeout(timer);
  if (decision) return;
  timer = setTimeout(() => {
    try {
      if (decision) return;
      machine.onTimeout();
      prevotes.clear();
      precommits.clear();
      activeProposal = null;
      publish("timeout", { note: "local_timeout", height: machine.height, round: machine.round });
      armTimeout();
      maybePropose();
    } catch (e) {
      errors.push(String(e.message || e));
    }
  }, machine.timeoutMs());
}

function maybePropose() {
  if (decision || machine.phase !== "propose") return;
  if (machine.expectedProposer() !== validatorId) return;
  const h = machine.height;
  const round = machine.round;
  const fields = proposalFields(
    committee, h, round, previousBlockHash, blockHashForPropose, validatorId,
  );
  const signature = crypto.sign(null, signedMessage("propose", fields), privateKey).toString("base64");
  const proposal = {
    height: h, round, previousBlockHash,
    blockHash: blockHashForPropose, proposerId: validatorId, signature,
  };
  publish("proposal", proposal);
}

function tryPrevoteQuorum() {
  if (machine.phase !== "prevote" || prevotes.size < committee.quorum) return;
  try {
    machine.onPrevoteQuorum(activeProposal, [...prevotes.values()]);
  } catch { return; }
  const pre = signPhaseVote(privateKey, committee, activeProposal, "precommit");
  precommits.set(pre.validatorId, pre);
  publish("precommit", pre);
  tryPrecommitQuorum();
  armTimeout();
}

function tryPrecommitQuorum() {
  if (machine.phase !== "precommit" || precommits.size < committee.quorum) return;
  try {
    const result = machine.onPrecommitQuorum(activeProposal, [...precommits.values()]);
    decision = result.decision;
    if (timer) clearTimeout(timer);
    parentPort.postMessage({
      kind: "decided",
      validatorId,
      decision,
      productionConsensus: false,
      researchOnly: true,
    });
  } catch { /* wait */ }
}

function onEnvelope(msg) {
  try {
    if (msg.chainId !== committee.chainId) return;
    if (msg.type === "proposal") {
      if (decision || msg.height !== machine.height || msg.round !== machine.round) return;
      if (machine.phase !== "propose") return;
      const proposal = msg.payload;
      machine.onProposal(proposal);
      activeProposal = proposal;
      prevotes.clear();
      precommits.clear();
      const vote = signPhaseVote(privateKey, committee, proposal, "prevote");
      prevotes.set(vote.validatorId, vote);
      publish("prevote", vote);
      tryPrevoteQuorum();
      armTimeout();
    } else if (msg.type === "prevote") {
      if (decision || !activeProposal) return;
      if (msg.height !== machine.height || msg.round !== machine.round) return;
      prevotes.set(msg.payload.validatorId, msg.payload);
      tryPrevoteQuorum();
    } else if (msg.type === "precommit") {
      if (decision || !activeProposal) return;
      if (msg.height !== machine.height || msg.round !== machine.round) return;
      precommits.set(msg.payload.validatorId, msg.payload);
      tryPrecommitQuorum();
    }
  } catch (e) {
    errors.push(String(e.message || e));
  }
}

parentPort.on("message", (m) => {
  if (m?.kind === "envelope") onEnvelope(m.envelope);
  else if (m?.kind === "stop") {
    if (timer) clearTimeout(timer);
    parentPort.postMessage({ kind: "stopped", validatorId, errors, decision });
  }
});

armTimeout();
maybePropose();
parentPort.postMessage({ kind: "ready", validatorId, researchOnly: true });
