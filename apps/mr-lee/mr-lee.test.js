"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { getConfig, authorize, checkPriviNetwork, askMrLee } = require("./core");
const { simulatePaperTrade } = require("./paper-trade");
const { makeMrLeeWebsiteHandler } = require("./website-adapter");

const trusted = "https://privi.example.org"; // used only in isolated synthetic tests
const fakeSecret = "TEST_ONLY_NOT_A_REAL_SECRET_0123456789abcdef";
const genesisHash = "0x" + "a".repeat(64);
const createEnv = (overrides = {}) => ({
  MR_LEE_ENABLED: "true",
  MR_LEE_ALLOWED_ORIGINS: trusted,
  MR_LEE_GATEWAY_TOKEN: fakeSecret,
  OPENAI_API_KEY: "FAKE_TEST_KEY_NOT_VALID_ANYWHERE_1234",
  PRIVI_MAINNET_EVM_CHAIN_ID: "400001",
  PRIVI_MAINNET_EVM_RPC_URL: "https://rpc.privi.example.org",
  PRIVI_EVM_GENESIS_BLOCK_HASH: genesisHash,
  ...overrides
});
function mockRPC({ cid = "0x61a81", block = "0x30", hash = genesisHash } = {}) {
  return async (_url, options) => {
    const method = JSON.parse(options.body).method;
    const result = method === "eth_chainId" ? cid
      : method === "eth_blockNumber" ? block
      : method === "eth_getBlockByNumber" ? { hash }
      : null;
    return { ok: true, async json() { return { jsonrpc: "2.0", id: 1, result }; } };
  };
}

test("Mr. Lee is strictly disabled by default", () => {
  const cfg = getConfig({});
  assert.equal(cfg.enabled, false);
  assert.equal(authorize(cfg, {}), false);
});

test("exposed TEST/BNB/synthetic/unknown genesis block financial activation", () => {
  for (const id of [1, 56, 97, 262144, 999991, 2026101601, 4221]) {
    assert.throws(() => getConfig(createEnv({ PRIVI_MAINNET_EVM_CHAIN_ID: String(id) })));
  }
  assert.throws(() => getConfig(createEnv({ PRIVI_EVM_GENESIS_BLOCK_HASH: "" })));
  assert.throws(() => getConfig(createEnv({ PRIVI_MAINNET_EVM_RPC_URL: "http://127.0.0.1:26657" })));
  assert.throws(() => getConfig(createEnv({ MR_LEE_ALLOWED_ORIGINS: "*" })));
  assert.throws(() => getConfig(createEnv({ OPENAI_API_KEY: "" })));
  assert.throws(() => getConfig(createEnv({ MR_LEE_GATEWAY_TOKEN: "" })));
});

test("website gateway needs private secret and exact origin; browser blocked", () => {
  const cfg = getConfig(createEnv());
  const headers = {
    authorization: "Bearer " + fakeSecret,
    "x-privi-website-origin": trusted
  };
  assert.equal(authorize(cfg, headers), true);
  assert.equal(authorize(cfg, { ...headers, origin: trusted }), false);
  assert.equal(authorize(cfg, { ...headers, "x-privi-website-origin": "https://evil.example" }), false);
  assert.equal(authorize(cfg, { ...headers, authorization: "Bearer wrong" }), false);
});

test("server-side RPC verifies exact chain ID, block production, and genesis", async () => {
  const cfg = getConfig(createEnv());
  const network = await checkPriviNetwork(cfg, mockRPC());
  assert.equal(network.ok, true);
  assert.equal(network.chainId, 400001);
  assert.equal(network.height, "48");
  assert.equal((await checkPriviNetwork(cfg, mockRPC({cid:"0x40000"}))).ok, false);
  assert.equal((await checkPriviNetwork(cfg, mockRPC({hash: "0x" + "b".repeat(64)}))).ok, false);
  assert.equal((await checkPriviNetwork(cfg, mockRPC({block: "0x0"}))).ok, false);
  assert.equal((await checkPriviNetwork(cfg, async () => { throw Error("offline"); })).ok, false);
});

test("OpenAI Responses API invoked only server side; no tools, no storage", async () => {
  const cfg = getConfig(createEnv());
  let request;
  const modelMock = async (url, options) => {
    request = { url, ...options };
    return { ok: true, async json() { return {
      output: [{ type:"message", role:"assistant",
        content:[{ type:"output_text", text:"Mr. Lee provides PRVI wallet help." }] }]
    }; } };
  };
  const result = await askMrLee(cfg, "How does the Privi wallet work?",
    "utility", {chainId:400001,height:"48"}, modelMock);
  assert.match(result,/wallet help/);
  const body = JSON.parse(request.body);
  assert.equal(request.url,"https://api.openai.com/v1/responses");
  assert.equal(body.store, false);
  assert.equal(body.tools, undefined);
  assert.equal(body.model, "gpt-4.1-mini");
  assert.match(body.instructions, /PAPER-TRADE/);
  await assert.rejects(askMrLee(cfg, "x", "trade_live", {}, modelMock));
});

test("paper trade is precise, nonexecuting and uses user-supplied prices", () => {
  const q = simulatePaperTrade({symbol:"PRVI/USDC",side:"buy",price:"0.35",quantity:"20"});
  assert.equal(q.notional,"7");
  assert.equal(q.estimated_fee,"0.007");
  assert.equal(q.mode,"paper_only");
  assert.equal(q.executed, false);
  assert.equal(q.quote_is_live, false);
  assert.throws(() => simulatePaperTrade({symbol:"PRVI/USDC",side:"buy",price:"0",quantity:"5"}));
  assert.throws(() => simulatePaperTrade({symbol:"PRVI/USDC",side:"withdraw",price:"1",quantity:"5"}));
  assert.throws(() => simulatePaperTrade({symbol:"PRVI/USDC",side:"buy",price:"0.1000001",quantity:"2"}));
});

test("website proxy denies anonymous sessions and cross-site origin", async () => {
  const handle = makeMrLeeWebsiteHandler({
    getAuthenticatedSession: async () => null,
    env: {
      MR_LEE_WEBSITE_ORIGIN: trusted,
      MR_LEE_PRIVATE_GATEWAY_URL: "https://private-gateway.example.org",
      MR_LEE_GATEWAY_TOKEN: fakeSecret
    }
  });
  const makeRequest = (origin) => new Request("https://privi.example.org/api/mr-lee/chat",{
    method:"POST", headers:{origin,"content-type":"application/json"},
    body:JSON.stringify({message:"Hi",category:"utility"})
  });
  assert.equal((await handle(makeRequest(trusted))).status,401);
  assert.equal((await handle(makeRequest("https://evil.example"))).status,403);
});

test("website proxy forwards identity and secret only from verified site server", async () => {
  let forwarded;
  const handle = makeMrLeeWebsiteHandler({
    getAuthenticatedSession: async () => ({ userId:"authenticated-1234" }),
    fetchImpl: async (url, req) => {
      forwarded = { url, ...req };
      return { status:200, async text() { return '{"reply":"Welcome"}'; } };
    },
    env: {
      MR_LEE_WEBSITE_ORIGIN: trusted,
      MR_LEE_PRIVATE_GATEWAY_URL:"https://private-gateway.example.org",
      MR_LEE_GATEWAY_TOKEN:fakeSecret
    }
  });
  const request = new Request("https://privi.example.org/api/mr-lee/chat",{
    method:"POST", headers:{origin:trusted,"content-type":"application/json"},
    body:'{"message":"Hi","category":"utility"}'
  });
  const res = await handle(request);
  assert.equal(res.status,200);
  assert.equal(forwarded.url,"https://private-gateway.example.org/internal/mr-lee/chat");
  assert.equal(forwarded.headers["X-Privi-User-Id"],"authenticated-1234");
  assert.equal(forwarded.headers.Authorization,"Bearer " + fakeSecret);
});

test("website proxy rejects missing real session verifier", () => {
  assert.throws(() => makeMrLeeWebsiteHandler({getAuthenticatedSession:null}));
});
