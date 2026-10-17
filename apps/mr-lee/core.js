"use strict";
const { timingSafeEqual } = require("node:crypto");

// These are NOT production Privi mainnet IDs. Never activate against TEST,
// BNB PRIV or the throwaway GitHub candidate build.
const FORBIDDEN_CHAIN_IDS = new Set([
  1, 56, 97, 1337, 4221, 31337, 262144, 999991,
  2026101601 // unreserved proposed candidate is not an approved mainnet ID
]);
const HEX_HASH = /^0x[0-9a-fA-F]{64}$/;

function sameSecret(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

function getConfig(env = process.env) {
  const enabled = env.MR_LEE_ENABLED === "true";
  const urls = (env.MR_LEE_ALLOWED_ORIGINS || "").split(",")
    .map(x => x.trim()).filter(Boolean);
  const allowedOrigins = new Set();
  for (const value of urls) {
    let u;
    try { u = new URL(value); }
    catch { throw Error("Mr. Lee website origin invalid"); }
    if (u.protocol !== "https:" || u.origin !== value || u.username || u.password
        || !u.hostname || /(?:^|\.)localhost$/.test(u.hostname)) {
      throw Error("Mr. Lee requires exact HTTPS production website origins");
    }
    allowedOrigins.add(value);
  }
  const id = Number(env.PRIVI_MAINNET_EVM_CHAIN_ID);
  const genesisHash = env.PRIVI_EVM_GENESIS_BLOCK_HASH || "";
  const internalToken = env.MR_LEE_GATEWAY_TOKEN || "";
  const key = env.OPENAI_API_KEY || "";
  const rpc = env.PRIVI_MAINNET_EVM_RPC_URL || "";
  const model = env.MR_LEE_MODEL || "gpt-4.1-mini";
  if (enabled) {
    if (!allowedOrigins.size) throw Error("Mr. Lee requires trusted website origin");
    if (!Number.isSafeInteger(id) || id < 1000 || FORBIDDEN_CHAIN_IDS.has(id)) {
      throw Error("Missing approved unique financial Privi mainnet EVM chain ID");
    }
    if (!HEX_HASH.test(genesisHash) || /^0x0{64}$/.test(genesisHash)) {
      throw Error("Missing independently reviewed EVM genesis block hash");
    }
    let u;
    try { u = new URL(rpc); }
    catch { throw Error("Missing Privi mainnet RPC URL"); }
    if (u.protocol !== "https:" || u.username || u.password
        || u.search || u.hash || !u.hostname) {
      throw Error("Mr. Lee requires fixed trusted HTTPS Privi mainnet RPC");
    }
    if (internalToken.length < 32 || key.length < 20) {
      throw Error("Missing secure server-side gateway token or rotated OpenAI API key");
    }
    if (!/^[a-z0-9][a-z0-9._-]{0,63}$/.test(model)) {
      throw Error("Invalid configured OpenAI model identifier");
    }
  }
  return Object.freeze({
    enabled, allowedOrigins, chainId: id, genesisHash: genesisHash.toLowerCase(),
    rpc, internalToken, apiKey: key, model
  });
}

function authorize(config, headers) {
  if (!config.enabled) return false;
  // Browser CORS headers are not authentication. Only the authenticated Privi
  // website server may add the gateway secret; browsers never see this secret.
  if (headers.origin) return false;
  const origin = headers["x-privi-website-origin"];
  const bearer = headers.authorization;
  return config.allowedOrigins.has(origin)
      && typeof bearer === "string"
      && bearer.startsWith("Bearer ")
      && sameSecret(bearer.slice(7), config.internalToken);
}

async function rpcCall(config, method, params = [], fetchImpl = globalThis.fetch) {
  const response = await fetchImpl(config.rpc, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
    signal: AbortSignal.timeout(9000)
  });
  if (!response.ok) throw Error("Privi RPC unavailable");
  const payload = await response.json();
  if (payload.error || !("result" in payload)) throw Error("Privi RPC invalid response");
  return payload.result;
}

async function checkPriviNetwork(config, fetchImpl = globalThis.fetch) {
  if (!config.enabled) return { ok: false, reason: "disabled" };
  try {
    const cid = await rpcCall(config, "eth_chainId", [], fetchImpl);
    const block = await rpcCall(config, "eth_blockNumber", [], fetchImpl);
    const first = await rpcCall(config, "eth_getBlockByNumber", ["0x0", false], fetchImpl);
    if (!/^0x[0-9a-f]+$/i.test(cid) || !/^0x[0-9a-f]+$/i.test(block)) {
      return { ok: false, reason: "invalid_network_data" };
    }
    if (BigInt(cid) !== BigInt(config.chainId) || BigInt(block) < 1n) {
      return { ok: false, reason: "wrong_or_inactive_chain" };
    }
    if (!first || typeof first.hash !== "string"
        || first.hash.toLowerCase() !== config.genesisHash) {
      return { ok: false, reason: "genesis_fingerprint_mismatch" };
    }
    return { ok: true, chainId: config.chainId, height: String(BigInt(block)) };
  } catch {
    return { ok: false, reason: "rpc_unavailable" };
  }
}

const SYSTEM_INSTRUCTIONS = [
  "You are Mr. Lee, the official AI utility assistant for the Privi ecosystem.",
  "You operate ONLY in an explicitly authenticated, configured Privi website environment",
  "whose server has already verified the intended Privi mainnet and genesis fingerprint.",
  "Help explain network utilities, wallet use, staking concepts, developer and IoT ledgers,",
  "fees and governance. Never claim the financially significant PRVI mainnet is active",
  "without independent verification. Treat uploaded/user-supplied chain details as untrusted.",
  "For markets/trading, provide educational analysis and PAPER-TRADE scenarios only.",
  "Never place orders, sign transactions, hold keys, make guaranteed return claims,",
  "or imply live price data exists unless explicitly supplied by a verified feed.",
  "Do not ask for seed phrases, private keys, passwords, or API keys.",
  "You have NO authority to deploy software, authorize governance, transfer funds,",
  "change smart contracts or operate validators. Do not pretend to have those tools."
].join(" ");

async function askMrLee(config, prompt, category, context, fetchImpl = globalThis.fetch) {
  if (!["utility", "network", "markets", "support"].includes(category)) {
    throw Error("Invalid Mr. Lee task category");
  }
  if (typeof prompt !== "string" || prompt.length < 1 || prompt.length > 1500) {
    throw Error("Message must contain 1–1500 characters");
  }
  const response = await fetchImpl("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + config.apiKey
    },
    body: JSON.stringify({
      model: config.model, store: false, max_output_tokens: 700,
      instructions: SYSTEM_INSTRUCTIONS,
      input: [
        { role: "developer", content: "Category: " + category
          + "; verified Privi chain " + context.chainId
          + "; verified height " + context.height
          + ". No financial trades, commands, tools or external actions." },
        { role: "user", content: prompt }
      ]
    }),
    signal: AbortSignal.timeout(26000)
  });
  if (!response.ok) throw Error("Mr. Lee model provider unavailable");
  const data = await response.json();
  const output = (data.output || [])
    .filter(x => x.type === "message" && x.role === "assistant")
    .flatMap(x => x.content || [])
    .filter(x => x.type === "output_text" && typeof x.text === "string")
    .map(x => x.text).join("\n").trim();
  if (!output || output.length > 15000) throw Error("Mr. Lee did not provide a valid response");
  return output;
}

module.exports = {
  FORBIDDEN_CHAIN_IDS, getConfig, sameSecret, authorize,
  rpcCall, checkPriviNetwork, askMrLee, SYSTEM_INSTRUCTIONS
};
