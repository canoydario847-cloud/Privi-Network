"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const {
  hash, signedMessage, parseRegistry, positionStamp, proposer,
  proposalFields, voteFields, TRUSTED_MODE,
} = require("./engine.cjs");
const {verifyLinkedResearchCertificates} = require("./linked_certificate_verifier.cjs");

function signer() {
  const key = crypto.generateKeyPairSync("ed25519");
  const der = key.publicKey.export({type: "spki", format: "der"});
  return {id: hash(der), pub: der.toString("base64"), priv: key.privateKey};
}
function sign(priv, kind, fields) {
  return crypto.sign(null, signedMessage(kind, fields), priv).toString("base64");
}
function fixture() {
  const root = signer();
  const validators = Array.from({length: 4}, signer);
  const chainId = "privi-pop-research-linked-blocks";
  const genesisHash = "0x" + "a".repeat(64);
  const epoch = 1;
  const registry = {
    mode: TRUSTED_MODE, chainId, genesisHash, epoch,
    validators: validators.map((v, i) => {
      const operatorId = "OPERATOR_" + i;
      const faultDomain = "region" + i + ".isolated.test";
      const companyId = "PRIVI_" + i, positionSequence = i + 1;
      const anchorBlockHash = hash(Buffer.from("research-position-" + i));
      return {
        id: v.id, keySpkiBase64: v.pub, operatorId, faultDomain,
        companyId, positionSequence, anchorBlockHash,
        positionHash: hash(Buffer.from(positionStamp(companyId, positionSequence))),
        admissionSignature: sign(root.priv, "admit", [
          chainId, genesisHash, epoch, operatorId, faultDomain, companyId,
          positionSequence, v.id, anchorBlockHash,
        ]),
      };
    }),
  };
  const committee = parseRegistry(registry, root.pub);
  const byId = new Map(validators.map(v => [v.id, v]));
  function block(height, previousBlockHash, blockHash, round = 0, votes = 3) {
    const proposerId = proposer(committee, height, round);
    const fields = proposalFields(committee, height, round,
      previousBlockHash, blockHash, proposerId);
    return {
      proposal: {
        height, round, previousBlockHash, blockHash, proposerId,
        signature: sign(byId.get(proposerId).priv, "propose", fields),
      },
      votes: committee.validators.slice(0, votes).map(v => ({
        validatorId: v.id,
        signature: sign(byId.get(v.id).priv, "commit", voteFields(fields, v.id)),
      })),
    };
  }
  const b1 = "0x" + "b".repeat(64), b2 = "0x" + "c".repeat(64),
    b3 = "0x" + "d".repeat(64);
  const chain = [block(1, genesisHash, b1), block(2, b1, b2), block(3, b2, b3)];
  return {committee, genesisHash, block, chain, b1, b2, b3};
}
function verify(f, overrides = {}) {
  return verifyLinkedResearchCertificates({
    committee: f.committee, anchorHeight: 0,
    anchorHash: f.genesisHash, bundles: f.chain, ...overrides,
  });
}

test("three contiguous independently signed research blocks verify without claiming finality", () => {
  const f = fixture();
  const result = verify(f);
  assert.deepEqual(result.checked.map(x => x.height), [1, 2, 3]);
  assert.equal(result.checked[2].quorum, 3);
  assert.equal(result.lastBlockHash, f.b3);
  assert.equal(result.productionFinality, false);
  assert.equal(result.productionConsensus, false);
  assert.equal(result.anchorTrustVerified, false);
  assert.equal(Object.isFrozen(result.checked), true);
});

test("research genesis anchor must match pinned committee genesis identity", () => {
  const f = fixture();
  assert.throws(() => verify(f, {anchorHash: f.b1}), /genesis anchor/);
});

test("reject skipped, duplicated and reordered block heights", () => {
  const f = fixture();
  const skipped = [f.chain[0], f.block(3, f.b1, f.b3)];
  assert.throws(() => verify(f, {bundles: skipped}), /height gap/);
  assert.throws(() => verify(f, {bundles: [f.chain[0], f.chain[0]]}), /height gap/);
  assert.throws(() => verify(f, {bundles: [...f.chain].reverse()}), /height gap/);
});

test("reject signed block-hash cycles, including a return to the pinned anchor", () => {
  const f = fixture();
  // Both malicious third-block proposals are signed by the correct proposer
  // and a quorum, and each references the correct immediate parent.
  const repeatsFirst = f.block(3, f.b2, f.b1);
  assert.throws(
    () => verify(f, {bundles: [f.chain[0], f.chain[1], repeatsFirst]}),
    /repeats an earlier block hash/
  );
  const returnsToGenesis = f.block(3, f.b2, f.genesisHash);
  assert.throws(
    () => verify(f, {bundles: [f.chain[0], f.chain[1], returnsToGenesis]}),
    /repeats an earlier block hash/
  );
});

test("valid signatures cannot bypass an incorrect parent link", () => {
  const f = fixture();
  const wrongParent = f.block(2, f.genesisHash, f.b2);
  assert.throws(() => verify(f, {bundles: [f.chain[0], wrongParent]}), /parent link/);
});

test("reject forged, replayed or insufficient signatures", () => {
  const f = fixture();
  const forged = structuredClone(f.chain);
  forged[1].votes[0].signature = forged[0].votes[0].signature;
  assert.throws(() => verify(f, {bundles: forged}), /Forged/);
  const inadequate = f.block(2, f.b1, f.b2, 0, 2);
  assert.throws(() => verify(f, {bundles: [f.chain[0], inadequate]}), /quorum/);
  const other = fixture();
  assert.throws(() => verify(f, {committee: other.committee}), /proposer|proposal|Forged/);
});

test("non-genesis anchor must be supplied explicitly and is never attested by checker", () => {
  const f = fixture();
  const result = verify(f, {
    anchorHeight: 1, anchorHash: f.b1, bundles: f.chain.slice(1),
  });
  assert.equal(result.anchorTrustVerified, false);
  assert.equal(result.anchorHeight, 1);
  assert.equal(result.lastHeight, 3);
});

test("research-only guard rejects production committee, overflow, empty and large batches", () => {
  const f = fixture();
  assert.throws(() => verify(f, {committee: {...f.committee, mode: "mainnet"}}), /research-only/);
  assert.throws(() => verify(f, {anchorHeight: -1}), /anchor height/);
  assert.throws(() => verify(f, {anchorHeight: Number.MAX_SAFE_INTEGER}), /anchor height/);
  assert.throws(() => verify(f, {bundles: []}), /1\.\.128/);
  assert.throws(() => verify(f, {bundles: Array(129).fill(f.chain[0])}), /1\.\.128/);
  assert.throws(() => verify(f, {bundles: [{proposal: {}, votes: "not-array"}]}), /Malformed/);
});
