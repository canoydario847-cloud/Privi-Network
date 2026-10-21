"use strict";
/*
 * Privi-only, fail-closed IoT submission. No keys are embedded.
 * Device signatures are authenticated off-chain; the on-chain gateway
 * authorization and sequence enforce order, not on-chain Ed25519 verification.
 */
const crypto = require("node:crypto");

const HEX32 = /^0x[0-9a-fA-F]{64}$/;
const ADDRESS = /^0x[0-9a-fA-F]{40}$/;
const POP_ZONES = new Set(["GRID/READINGS","FLEET/ASSETS","ENERGY/READINGS","IOT/GENERAL","ASSETS/VALUE"]);
const FORBIDDEN_EVM_CHAINS = new Set([
  1, 10, 56, 97, 137, 250, 42161, 43114, 8453, 84532, 11155111
]);

const sha = value => "0x" + crypto.createHash("sha256").update(value).digest("hex");
const bytes = hex => Buffer.from(hex.slice(2), "hex");

function must(ok, message) {
  if (!ok) throw new Error(message);
}

function canonical(value, depth = 0) {
  must(depth <= 16, "Payload nesting is too deep");
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    must(Number.isFinite(value) && Number.isSafeInteger(value), "Only safe integer payload numbers allowed");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return "[" + value.map(item => canonical(item, depth + 1)).join(",") + "]";
  }
  must(value && typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype,
       "Payload must be plain JSON");
  const keys = Object.keys(value).sort();
  return "{" + keys.map(k => {
    must(value[k] !== undefined, "Undefined payload properties forbidden");
    return JSON.stringify(k) + ":" + canonical(value[k], depth + 1);
  }).join(",") + "}";
}

function packetDigest(packet) {
  must(packet && typeof packet === "object" && !Array.isArray(packet), "Invalid event packet");
  must(packet.version === 3, "PoP-v3 signed event required");
  must(typeof packet.companyId === "string" && /^[A-Z0-9_-]{1,24}$/.test(packet.companyId),
       "Privi PoP company ID required");
  must(typeof packet.popZone === "string" && POP_ZONES.has(packet.popZone),
       "Invalid Privi PoP zone");
  must(typeof packet.deviceId === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(packet.deviceId),
       "Invalid device identifier");
  must(Number.isSafeInteger(packet.sequence) && packet.sequence > 0, "Invalid sequence");
  must(Number.isSafeInteger(packet.positionSequence) && packet.positionSequence > 0,
       "Invalid company-zone PoP position sequence");
  must(Number.isSafeInteger(packet.observedAt) && packet.observedAt > 0, "Invalid observation timestamp");
  must(typeof packet.eventType === "string" &&
       /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/.test(packet.eventType), "Invalid event type");
  must(packet.payload !== null && typeof packet.payload === "object" && !Array.isArray(packet.payload),
       "Payload must be a JSON object");
  const payloadText = canonical(packet.payload);
  must(Buffer.byteLength(payloadText) <= 16384, "Payload too large");
  const payloadHash = sha(Buffer.from(payloadText, "utf8"));
  const popStamp = `PoP:${packet.companyId}:${packet.popZone}:${String(packet.positionSequence).padStart(6,"0")}`;
  const signingText = JSON.stringify([
    packet.version, packet.companyId, packet.deviceId, packet.sequence,
    packet.positionSequence, packet.observedAt, packet.popZone,
    popStamp, packet.eventType, payloadHash
  ]);
  return {
    signingText,
    eventHash: sha(Buffer.from(signingText, "utf8")),
    deviceIdHash: sha(Buffer.from(packet.deviceId, "utf8")),
    companyIdHash: sha(Buffer.from(packet.companyId, "utf8")),
    popStamp, popStampHash: sha(Buffer.from(popStamp, "utf8")),
    popZoneHash: sha(Buffer.from(packet.popZone, "utf8")),
    eventTypeHash: sha(Buffer.from(packet.eventType, "utf8")),
    payloadHash
  };
}

function verifyDevicePacket(packet, registry) {
  const digest = packetDigest(packet);
  must(registry && Object.hasOwn(registry, packet.deviceId), "Device not authorized");
  const entry = registry[packet.deviceId];
  must(entry && typeof entry.publicKeySpkiBase64 === "string", "Missing enrolled device key");
  must(typeof packet.signatureBase64 === "string" &&
       /^[A-Za-z0-9+/]+={0,2}$/.test(packet.signatureBase64), "Bad signature encoding");
  const signature = Buffer.from(packet.signatureBase64, "base64");
  must(signature.length === 64 &&
       signature.toString("base64") === packet.signatureBase64, "Invalid Ed25519 signature length");
  const der = Buffer.from(entry.publicKeySpkiBase64, "base64");
  must(der.length > 0 && der.toString("base64") === entry.publicKeySpkiBase64,
       "Invalid public key encoding");
  const key = crypto.createPublicKey({key: der, format: "der", type: "spki"});
  must(key.asymmetricKeyType === "ed25519", "Ed25519 public key required");
  must(crypto.verify(null, Buffer.from(digest.signingText, "utf8"), key, signature),
       "Device signature rejected");
  return {
    ...digest,
    signingKeyHash: sha(der),
    signatureHash: sha(signature),
    sequence: BigInt(packet.sequence),
    positionSequence: BigInt(packet.positionSequence),
    observedAt: BigInt(packet.observedAt)
  };
}

function validateNetworkConfig(config) {
  must(config && config.network === "privi-native" && config.settlementChain === "privi",
       "Only native Privi settlement is supported");
  must(config.bridgeMode === "disabled" && config.pairingMode === "disabled",
       "Privi IoT integration forbids automatic external bridges or token pairs");
  must(config.mode === "development",
       "Production IoT submission blocked until canonical Privi mainnet identity and audits");
  must(config && Number.isSafeInteger(config.chainId) && config.chainId > 0,
       "Expected Privi EVM chain ID required");
  must(!FORBIDDEN_EVM_CHAINS.has(config.chainId), "Third-party EVM chains are prohibited");
  must(config.chainId === 262144,
       "Only Privi disposable developer EVM identity allowed before audited native mainnet");
  must(HEX32.test(config.genesisHash), "Pinned Privi genesis block hash required");
  must(ADDRESS.test(config.contractAddress), "Privi IoT contract address required");
  must(HEX32.test(config.contractCodeSha256), "Pinned contract bytecode SHA-256 required");
  must(typeof config.rpcUrl === "string", "RPC URL required");
  const url = new URL(config.rpcUrl);
  must(url.username === "" && url.password === "" && url.search === "" && url.hash === "",
       "RPC must not contain credentials or query strings");
  must(["127.0.0.1", "localhost", "::1"].includes(url.hostname) &&
       (url.protocol === "http:" || url.protocol === "https:"),
       "Disposable Privi developer RPC must remain on loopback");
  must(Number.isSafeInteger(config.confirmations) &&
       config.confirmations >= 1 && config.confirmations <= 20, "Confirmations must be 1..20");
  return config;
}

async function assertPriviChain(provider, config) {
  validateNetworkConfig(config);
  const observed = await provider.send("eth_chainId", []);
  must(typeof observed === "string" && /^0x[0-9a-f]+$/i.test(observed) &&
       BigInt(observed) === BigInt(config.chainId), "RPC is not the configured Privi chain");
  const genesis = await provider.send("eth_getBlockByNumber", ["0x0", false]);
  must(genesis && typeof genesis.hash === "string" &&
       genesis.hash.toLowerCase() === config.genesisHash.toLowerCase(),
       "RPC genesis does not match pinned Privi genesis");
  const code = await provider.send("eth_getCode", [config.contractAddress, "latest"]);
  must(typeof code === "string" && /^0x(?:[0-9a-f]{2})+$/i.test(code),
       "Privi IoT contract code missing");
  must(sha(bytes(code)).toLowerCase() === config.contractCodeSha256.toLowerCase(),
       "Privi IoT runtime code differs from pinned deployment");
}

function field(row, name, index) {
  return row && row[name] !== undefined ? row[name] : row[index];
}

async function submitEvent(packet, {registry, config, provider, wallet, contract,
                                    intentCapsule, ethers}) {
  const event = verifyDevicePacket(packet, registry);
  await assertPriviChain(provider, config); // always check before any signed transaction
  must(wallet && ADDRESS.test(wallet.address), "Gateway wallet required");
  must(contract && wallet.provider === provider && contract.runner === wallet,
       "Gateway signer and contract must use the pinned Privi provider");
  must(typeof contract.developers === "function" && typeof contract.devices === "function" &&
       typeof contract.companies === "function" && typeof contract.companyGateways === "function" &&
       typeof contract.nextPositionSequence === "function" &&
       typeof contract.recordEvent === "function" &&
       contract.interface && typeof contract.interface.parseLog === "function",
       "Verified Privi IoT contract interface required");
  const deployed = await contract.getAddress();
  must(typeof deployed === "string" &&
       deployed.toLowerCase() === config.contractAddress.toLowerCase(), "Wrong contract target");
  const developer = await contract.developers(wallet.address);
  must(field(developer, "registered", 0) === true &&
       field(developer, "enabled", 1) === true,
       "Privi developer registration missing or revoked");
  const company = await contract.companies(event.companyIdHash);
  must(field(company, "registered", 1) === true && field(company, "enabled", 2) === true,
       "Company must be registered and enabled on Privi");
  const companyAuthorized = await contract.companyGateways(event.companyIdHash, wallet.address);
  must(companyAuthorized === true, "Company administrator has not authorized this Privi developer gateway");
  const device = await contract.devices(event.deviceIdHash);
  must(field(device, "enrolled", 4) === true && field(device, "enabled", 3) === true,
       "Device not enrolled or disabled on Privi");
  must(String(field(device, "gateway", 0)).toLowerCase() === wallet.address.toLowerCase(),
       "Gateway not authorized for this device on Privi");
  must(String(field(device, "signingKeyHash", 1)).toLowerCase() === event.signingKeyHash.toLowerCase(),
       "Device key does not match the Privi enrollment");
  must(String(field(device, "companyIdHash", 5)).toLowerCase() === event.companyIdHash.toLowerCase(),
       "Privi PoP company position does not match device enrollment");
  must(BigInt(field(device, "lastSequence", 2)) + 1n === event.sequence,
       "Device sequence is not the next Privi transaction");
  const nextPosition = await contract.nextPositionSequence(event.companyIdHash, event.popZoneHash);
  must(BigInt(nextPosition) === event.positionSequence,
       "PoP company-zone position is not the next Privi ledger position");

  // Non-Turing-complete, signed Privi Intent Capsule (opt-in development
  // preview) adds company-specific rules without deploying business code.
  // When required by gateway configuration, omission is fail-closed.
  must(config.requireIntentCapsules === undefined ||
       typeof config.requireIntentCapsules === "boolean",
       "Privi Intent Capsule policy flag must be boolean");
  must(!config.requireIntentCapsules || intentCapsule,
       "Privi Intent Capsule is required by this development gateway");
  let intent;
  if (intentCapsule) {
    const {verifyIntentCapsule} = require("../intents/capsule.cjs");
    intent = await verifyIntentCapsule({
      ...intentCapsule,event,packet,config,wallet,contract,provider,ethers
    });
  }
  const fields = [
    event.deviceIdHash, event.sequence, event.observedAt,
    event.eventTypeHash, event.payloadHash, event.eventHash, event.signatureHash,
    event.popStampHash, event.popZoneHash, event.positionSequence
  ];
  // EIP-191 company approval includes maximum gas price and gas limit.
  // The entire bounded pair is submitted as the actual EVM tx overrides.
  if (intent) fields.push(intent.overrides);
  const tx = await contract.recordEvent(...fields);
  must(tx && /^0x[0-9a-fA-F]{64}$/.test(tx.hash) && typeof tx.wait === "function",
       "No Privi transaction hash returned");
  const receipt = await tx.wait(config.confirmations);
  must(receipt && Number(receipt.status) === 1, "Privi transaction not confirmed successful");
  must(typeof receipt.blockNumber === "number" && Number.isSafeInteger(receipt.blockNumber) && receipt.blockNumber > 0 &&
       typeof receipt.blockHash === "string" && HEX32.test(receipt.blockHash),
       "A mined Privi block hash and height are required");
  const receiptBlock = await provider.send("eth_getBlockByNumber",
    ["0x" + receipt.blockNumber.toString(16), false]);
  must(receiptBlock && typeof receiptBlock.hash === "string" &&
       receiptBlock.hash.toLowerCase() === receipt.blockHash.toLowerCase() &&
       typeof receiptBlock.timestamp === "string" && /^0x[0-9a-f]+$/i.test(receiptBlock.timestamp),
       "Privi receipt block cannot be verified");
  const blockTime = Number(BigInt(receiptBlock.timestamp));
  must(Number.isSafeInteger(blockTime) && blockTime > 0, "Invalid Privi sealed block timestamp");
  const matched = (receipt.logs || []).some(log => {
    if (!log || String(log.address).toLowerCase() !== config.contractAddress.toLowerCase()) return false;
    try {
      const decoded = contract.interface.parseLog(log);
      return decoded && decoded.name === "IoTRecorded" &&
             String(decoded.args.deviceIdHash || decoded.args[0]).toLowerCase() === event.deviceIdHash.toLowerCase() &&
             BigInt(decoded.args.sequence || decoded.args[1]) === event.sequence &&
             String(decoded.args.eventHash || decoded.args[2]).toLowerCase() === event.eventHash.toLowerCase() &&
             String(decoded.args.popStampHash || decoded.args[7]).toLowerCase() === event.popStampHash.toLowerCase() &&
             BigInt(decoded.args.positionSequence ?? decoded.args[9]) === event.positionSequence;
    } catch (_) { return false; }
  });
  must(matched, "Missing matching Privi IoTRecorded receipt log");
  return {chainId: config.chainId, transactionHash: tx.hash, blockNumber: receipt.blockNumber,
          blockTimestamp: blockTime, blockHash: receipt.blockHash,
          deviceIdHash: event.deviceIdHash, payloadHash: event.payloadHash,
          eventHash: event.eventHash, sequence: packet.sequence,
          positionSequence: packet.positionSequence,
          popStamp: event.popStamp, popStampHash: event.popStampHash,
          popZoneHash: event.popZoneHash, companyIdHash: event.companyIdHash,
          confirmations: config.confirmations,
          ...(intent ? {intentCapsuleDigest:intent.capsuleDigest,
                        intentWorstCaseFeeWei:intent.worstCaseFeeWei}: {})};
}

module.exports = {sha, canonical, packetDigest, verifyDevicePacket, validateNetworkConfig,
                  assertPriviChain, submitEvent, FORBIDDEN_EVM_CHAINS, POP_ZONES};
