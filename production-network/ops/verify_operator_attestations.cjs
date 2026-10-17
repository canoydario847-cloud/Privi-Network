#!/usr/bin/env node
"use strict";
/*
 * Verify independent operators' OFF-CHAIN Ed25519 attestation of a candidate
 * public TESTnet genesis. Does NOT attest legal identity, consensus key custody,
 * node independence, production readiness or financial mainnet authorization.
 * Never accepts or stores private keys.
 */
const fs = require("node:fs");
const crypto = require("node:crypto");
const { URL } = require("node:url");

const HEX40 = /^[\da-fA-F]{40}$/;
const HEX64 = /^[\da-fA-F]{64}$/;
const BASE64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;

function checked(condition, message) {
  if (!condition) throw new Error(message);
}
function httpsUrl(s) {
  if (typeof s !== "string") return false;
  try {
    const u = new URL(s);
    return u.protocol === "https:" && Boolean(u.hostname) && !u.username && !u.password &&
      !u.hash && !u.search;
  } catch (_) { return false; }
}
function validateHeader(m) {
  checked(m && typeof m === "object" && !Array.isArray(m), "manifest must be object");
  checked(m.network_type === "public_testnet" && m.asset_symbol === "TEST" &&
          m.valueless_asset === true && m.financial_mainnet_live === false &&
          m.bnb_priv_separate === true, "strict valueless TEST network metadata required");
  checked(typeof m.cosmos_chain_id === "string" &&
          /^[a-z0-9][a-z0-9-]{3,79}$/.test(m.cosmos_chain_id) &&
          m.cosmos_chain_id !== "local-4221", "valid non-demo Cosmos testnet ID required");
  checked(Number.isSafeInteger(m.evm_chain_id) && m.evm_chain_id > 0 &&
          ![1,56,97,4221,262144].includes(m.evm_chain_id), "valid non-demo EVM ID required");
  for (const field of ["genesis_sha256", "binary_sha256"]) {
    checked(typeof m[field] === "string" && HEX64.test(m[field]), "invalid " + field);
  }
}
function validateOperator(o) {
  checked(o && typeof o === "object" && !Array.isArray(o), "invalid operator");
  checked(typeof o.operator_id === "string" &&
          /^[a-zA-Z0-9._-]{3,64}$/.test(o.operator_id), "invalid operator_id");
  checked(typeof o.consensus_address === "string" && HEX40.test(o.consensus_address),
          "invalid CometBFT consensus address");
  checked(typeof o.fault_domain === "string" && /^[a-zA-Z0-9._:/-]{3,128}$/.test(o.fault_domain),
          "invalid fault_domain");
  checked(o.operator_controls_keys === true, "operator must claim key control");
  checked(httpsUrl(o.independence_attestation_url),
          "invalid operator evidence URL");
  checked(typeof o.attested_utc === "string" &&
          /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(o.attested_utc) &&
          Number.isFinite(Date.parse(o.attested_utc)) &&
          new Date(o.attested_utc).toISOString() === o.attested_utc.replace(/Z$/, ".000Z"),
          "invalid UTC attestation timestamp");
}
function payload(m, o) {
  validateHeader(m);
  validateOperator(o);
  // A versioned ordered-array encoding avoids ambiguous newlines and field
  // order in JSON objects. Every field is covered by the off-chain signature.
  return Buffer.from(JSON.stringify([
    "Privi public TESTnet operator attestation v1",
    m.cosmos_chain_id, m.evm_chain_id,
    m.genesis_sha256.toLowerCase(), m.binary_sha256.toLowerCase(),
    o.operator_id, o.consensus_address.toUpperCase(), o.fault_domain,
    o.independence_attestation_url, o.operator_controls_keys, o.attested_utc
  ]), "utf8");
}
function verify(m) {
  validateHeader(m);
  checked(Array.isArray(m.operators) && m.operators.length >= 4,
          "at least four operator attestations required");
  const uniqueIds = new Set(), uniqueAddresses = new Set();
  const uniqueDomains = new Set(), uniqueKeys = new Set();
  const outputs = [];
  for (const o of m.operators) {
    const bytes = payload(m, o);
    checked(typeof o.attestation_public_key_pem === "string" &&
            o.attestation_public_key_pem.length < 10240, "missing public attestation key");
    let key;
    try { key = crypto.createPublicKey(o.attestation_public_key_pem); }
    catch (_) { throw new Error("invalid public attestation key for " + o.operator_id); }
    checked(key.asymmetricKeyType === "ed25519", "attestation must use Ed25519");
    const fingerprint = crypto.createHash("sha256").update(
      key.export({type:"spki",format:"der"})).digest("hex");
    checked(typeof o.attestation_signature_base64 === "string" &&
            o.attestation_signature_base64.length > 0 &&
            o.attestation_signature_base64.length < 1000 &&
            BASE64.test(o.attestation_signature_base64),
            "missing or invalid detached signature for " + o.operator_id);
    const sig = Buffer.from(o.attestation_signature_base64, "base64");
    checked(sig.length === 64 &&
            crypto.verify(null, bytes, key, sig),
            "invalid operator attestation signature for " + o.operator_id);
    const entries = [
      [uniqueIds, o.operator_id.toLowerCase(), "operator ID"],
      [uniqueAddresses, o.consensus_address.toUpperCase(), "consensus address"],
      [uniqueDomains, o.fault_domain.toLowerCase(), "fault domain"],
      [uniqueKeys, fingerprint, "off-chain public attestation key"]
    ];
    for (const [set, value, field] of entries) {
      checked(!set.has(value), "duplicate " + field);
      set.add(value);
    }
    outputs.push({operator_id:o.operator_id,consensus_address:o.consensus_address.toUpperCase(),
      attestation_key_sha256:fingerprint,signature_valid:true});
  }
  return {
    status:"VALID_OFFCHAIN_ATTESTATIONS_ONLY",
    cosmos_chain_id:m.cosmos_chain_id, evm_chain_id:m.evm_chain_id,
    genesis_sha256:m.genesis_sha256.toLowerCase(),
    verified_attestation_count:outputs.length,
    operators:outputs,
    warning:"Only cryptographic control of separate off-chain keys. Independent legal identity, actual validator consensus keys/ownership, security, genesis contents, node operation and PRVI mainnet launch are NOT verified."
  };
}
function main(args) {
  checked(args.length === 1 || (args.length === 3 && args[1] === "--payload"),
    "Usage: node verify_operator_attestations.cjs manifest.json [--payload operator_id]");
  const manifest = JSON.parse(fs.readFileSync(args[0], "utf8"));
  if (args.length === 3) {
    checked(Array.isArray(manifest.operators), "operators array required");
    const operator = manifest.operators.find(o => o && o.operator_id === args[2]);
    checked(operator, "requested operator not found");
    process.stdout.write(payload(manifest, operator)); // no newline; sign exact bytes
  } else {
    process.stdout.write(JSON.stringify(verify(manifest), null, 2) + "\n");
  }
}
if (require.main === module) {
  try { main(process.argv.slice(2)); }
  catch (e) { console.error("NO-GO: " + e.message); process.exitCode = 1; }
}
module.exports = {payload,verify,validateHeader,validateOperator};
