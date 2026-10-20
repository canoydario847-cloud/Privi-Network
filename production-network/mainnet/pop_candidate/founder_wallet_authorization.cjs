"use strict";
/*
 * RESEARCH ONLY. This prevents treating a copied Privi owner EVM address
 * as proof that Dario Canoy actually signed a candidate validator committee.
 * This module is NOT installed in Cosmos EVM / CometBFT consensus, does not
 * create PoP finality, and never signs on behalf of the founder.
 *
 * A real founder EIP-191 personal_sign over the exact canonical challenge
 * would be needed. No founder signature or private key is present in GitHub.
 * Tests use unrelated ephemeral wallets; they never impersonate the founder.
 */
const crypto = require("node:crypto");
const {
  parseRegistry, OWNER_EVM_WALLET, OWNER_OPERATOR_ID, TRUSTED_MODE
} = require("./engine.cjs");

const DOMAIN = "Privi/PoP/OwnerAuthorization/RESEARCH/v1";
const NONCE = /^0x[0-9a-f]{64}$/;
const SIGNATURE = /^0x[0-9a-fA-F]{130}$/;
const MAX_LIFETIME_SECONDS = 7 * 24 * 3600;

function requireThat(value, message) { if (!value) throw Error(message); }
function sha256(value) {
  return "0x" + crypto.createHash("sha256").update(value).digest("hex");
}

/** Sorted committee digest never depends on JS key iteration order. */
function committeeFingerprint(committee, governancePublicKeySpkiBase64) {
  requireThat(committee.mode === TRUSTED_MODE && committee.ownerWallet === OWNER_EVM_WALLET &&
    committee.operatorId === OWNER_OPERATOR_ID,
  "Unauthorized or non-research Privi committee");
  requireThat(typeof governancePublicKeySpkiBase64 === "string",
              "PoP admission signing key missing");
  const committeeRows = committee.validators.map(v => [
    v.id, v.operatorId, v.faultDomain, v.stamp, v.positionHash, v.anchorBlockHash
  ]);
  return sha256(Buffer.from(JSON.stringify([
    DOMAIN, committee.chainId, committee.genesisHash, committee.epoch,
    committee.ownerWallet, committee.operatorId,
    governancePublicKeySpkiBase64, committeeRows
  ]), "utf8"));
}

function validateChallengeFields(approval) {
  requireThat(approval && typeof approval === "object" && !Array.isArray(approval),
    "Founder owner approval is absent");
  requireThat(typeof approval.nonce === "string" && NONCE.test(approval.nonce) &&
              approval.nonce !== "0x" + "0".repeat(64),
              "Research authorization needs a unique nonzero 32-byte nonce");
  requireThat(Number.isSafeInteger(approval.expiresAtSeconds) &&
              approval.expiresAtSeconds > 0,
              "Research authorization expiry must be an integer Unix timestamp");
}

/**
 * Only the message returned here should be signed using a wallet's personal
 * sign interface. Caller must inspect the chain, governance key, committee
 * fingerprint, nonce and expiry before signing.
 */
function buildChallenge(registry, governancePublicKeySpkiBase64, approval) {
  validateChallengeFields(approval);
  const committee = parseRegistry(registry, governancePublicKeySpkiBase64);
  const committeeHash = committeeFingerprint(committee, governancePublicKeySpkiBase64);
  const message = [
    DOMAIN,
    "RESEARCH ONLY — NOT MAINNET OR A FINANCIAL AUTHORIZATION",
    "ownerWallet=" + OWNER_EVM_WALLET,
    "operator=" + OWNER_OPERATOR_ID,
    "researchChain=" + committee.chainId,
    "genesis=" + committee.genesisHash,
    "epoch=" + committee.epoch,
    "committeeSHA256=" + committeeHash,
    "nonce=" + approval.nonce,
    "expiresAtUnixSeconds=" + approval.expiresAtSeconds
  ].join("\n");
  return Object.freeze({committee, committeeHash, message});
}

/** Positive unit tests may use ephemeral wallets for this generic primitive.
 * The actual founder gate below ALWAYS pins the real founder EVM address.
 */
function verifyEip191Signer(message, signature, expectedWallet, ethers) {
  requireThat(typeof message === "string" && message.startsWith(DOMAIN + "\n"),
      "Research EIP-191 domain required");
  requireThat(typeof signature === "string" && SIGNATURE.test(signature),
      "Malformed EIP-191 owner signature");
  requireThat(ethers && typeof ethers.verifyMessage === "function" &&
    typeof ethers.getAddress === "function", "Ethers v6 signature verifier required");
  requireThat(typeof expectedWallet === "string" && /^0x[0-9a-fA-F]{40}$/.test(expectedWallet),
    "Expected EVM signer is missing");
  let recovered;
  try { recovered = ethers.verifyMessage(message, signature); }
  catch (_) { throw Error("Invalid research owner EIP-191 signature"); }
  requireThat(recovered.toLowerCase() === expectedWallet.toLowerCase(),
    "EIP-191 signature is not from the required Privi wallet");
  return recovered;
}

/**
 * This is the ONLY candidate wallet-authorization entrypoint.
 * No callback, alternate wallet, or detached declaration can bypass founder
 * EVM signature verification. It cannot verify governance ownership of a
 * contract wallet (EIP-1271) and cannot establish that the real founder
 * controls the EVM address without a real owner signature.
 */
function verifyFounderResearchAuthorization({
  registry, governancePublicKeySpkiBase64, approval, ethers,
  nowSeconds = Math.floor(Date.now() / 1000)
}) {
  const {committee, committeeHash, message} =
    buildChallenge(registry, governancePublicKeySpkiBase64, approval);
  requireThat(Number.isSafeInteger(nowSeconds) && nowSeconds > 0,
    "Research verification requires a valid current time");
  requireThat(approval.expiresAtSeconds > nowSeconds &&
    approval.expiresAtSeconds <= nowSeconds + MAX_LIFETIME_SECONDS,
    "Research owner signature expired or exceeds 7-day validity");
  verifyEip191Signer(message, approval.signature, OWNER_EVM_WALLET, ethers);
  return Object.freeze({
    ownerWallet: OWNER_EVM_WALLET,
    authorizedCommitteeHash: committeeHash,
    researchChain: committee.chainId,
    epoch: committee.epoch,
    expiry: approval.expiresAtSeconds,
    ownerCryptographicallyVerified: true,
    productionConsensus: false
  });
}
module.exports = {
  DOMAIN, MAX_LIFETIME_SECONDS, committeeFingerprint,
  buildChallenge, verifyEip191Signer, verifyFounderResearchAuthorization
};
