#!/usr/bin/env node
"use strict";
/**
 * One signed device JSON packet in on stdin -> exactly one Privi EVM call.
 * No HTTP listener, bridging, auto-mint, or live mainnet activation.
 *
 * Development-only transaction submission is opt-in. Always pins chain ID,
 * genesis, contract address and runtime bytecode before sending.
 */
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { submitEvent, verifyDevicePacket, validateNetworkConfig } = require("./core.cjs");

const ABI = [
  "function devices(bytes32) view returns (address gateway, bytes32 signingKeyHash, uint64 lastSequence, bool enabled, bool enrolled)",
  "function recordEvent(bytes32 deviceIdHash,uint64 sequence,uint64 observedAt,bytes32 eventTypeHash,bytes32 payloadHash,bytes32 eventHash,bytes32 signatureHash)",
  "event IoTRecorded(bytes32 indexed deviceIdHash,uint64 indexed sequence,bytes32 indexed eventHash,bytes32 payloadHash,bytes32 eventTypeHash,bytes32 signatureHash,uint64 observedAt)"
];

function parseFile(envKey, maxSize = 131072) {
  const file = process.env[envKey];
  if (!file || typeof file !== "string") throw Error("Missing " + envKey);
  const stat = fs.statSync(file);
  if (!stat.isFile() || stat.size > maxSize) throw Error("Invalid " + envKey + " file size");
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function loadPacket() {
  let raw = "";
  const max = 65536;
  const buffer = Buffer.alloc(8192);
  while (true) {
    const bytes = fs.readSync(0, buffer, 0, buffer.length);
    if (bytes === 0) break;
    raw += buffer.subarray(0, bytes).toString("utf8");
    if (Buffer.byteLength(raw) > max) throw Error("Device event exceeds 64 KiB");
  }
  return JSON.parse(raw);
}

async function run() {
  const packet = loadPacket();
  const registry = parseFile("PRIVI_IOT_DEVICE_REGISTRY");
  const config = validateNetworkConfig(parseFile("PRIVI_IOT_CHAIN_CONFIG"));
  const verified = verifyDevicePacket(packet, registry);
  const quoteHint = {
    packetHash: verified.eventHash, deviceIdHash: verified.deviceIdHash,
    note: "No financial token is minted or issued by Privi IoT events"
  };

  if (process.env.PRIVI_IOT_ENABLE_SUBMISSION !== "DEV_ONLY") {
    console.log(JSON.stringify({
      status: "VALID_SIGNED_PACKET_PREVIEW_ONLY", ...quoteHint,
      chainId: config.chainId, warning: "No blockchain transaction submitted"
    }));
    return;
  }
  if (config.mode !== "development") {
    throw Error("Financial/production submission is not enabled; independent audit required");
  }
  if (!process.env.PRIVI_IOT_GATEWAY_PRIVATE_KEY) {
    throw Error("Developer gateway key must be supplied securely through environment");
  }

  // ethers must be installed by the operator into an isolated Node package.
  const ethers = require("ethers");
  const provider = new ethers.JsonRpcProvider(config.rpcUrl, undefined, { staticNetwork: false });
  const wallet = new ethers.Wallet(process.env.PRIVI_IOT_GATEWAY_PRIVATE_KEY, provider);
  const contract = new ethers.Contract(config.contractAddress, ABI, wallet);
  const confirmation = await submitEvent(packet, { registry, config, provider, wallet, contract });
  // Print the durable receipt even if optional local indexing fails afterwards.
  console.log(JSON.stringify({ status: "PRIVI_TEST_EVENT_CONFIRMED", ...confirmation, ...quoteHint }));

  if (process.env.PRIVI_IOT_DB_PATH) {
    const python = process.env.PRIVI_IOT_PYTHON || "python3";
    const script = path.join(__dirname, "..", "ai_data_db.py");
    const child = spawnSync(python, [script, "record", "--db", process.env.PRIVI_IOT_DB_PATH], {
      input: JSON.stringify({ packet, confirmation }),
      encoding: "utf8",
      timeout: 20000,
      maxBuffer: 8192,
      env: { PATH: process.env.PATH || "/usr/bin:/bin" }
    });
    if (child.error || child.status !== 0) {
      console.error("Privi transaction was confirmed but local AI index failed. "
        + "Reconcile using the transaction receipt before retrying.");
      process.exitCode = 3;
    } else {
      console.log(JSON.stringify({
        status: "PRIVI_TEST_EVENT_AI_INDEXED", ...JSON.parse(child.stdout)
      }));
    }
  }
}

if (require.main === module) {
  run().catch(e => {
    const description = e && /signature|sequence|chain|config|device|receipt|genesis|contract/i.test(String(e.message))
      ? String(e.message).slice(0, 180) : "operation rejected";
    console.error("Privi IoT gateway: " + description);
    process.exitCode = 2;
  });
}

module.exports = { ABI, loadPacket };
