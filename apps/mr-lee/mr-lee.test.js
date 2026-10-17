"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { getConfig, checkPriviNetwork, askMrLee } = require("./core");
const { simulatePaperTrade } = require("./paper-trade");
const { makeMrLeeWebsiteHandler, SESSION_MAX_AGE_MS } = require("./website-adapter");
const { signedHeaders, verifyRequest, NonceCache, containsCredentialLikeText } = require("./security");

const trusted = "https://privi.example.org"; // synthetic, never actual financial chain
const fakeSecret = "TEST_ONLY_64_CHARACTER_SECRET_0123456789abcdef0123456789abcdef";
const genesisHash = "0x" + "a".repeat(64);
const NOW = 1792245600000;
const route = "/internal/mr-lee/chat";
const raw = '{"message":"How does the Privi wallet work?","category":"utility"}';
const userId = "test-opaque-id-123456789";
const createEnv = (overrides = {}) => ({
  MR_LEE_ENABLED: "true", MR_LEE_ALLOWED_ORIGINS: trusted,
  MR_LEE_GATEWAY_TOKEN: fakeSecret,
  OPENAI_API_KEY: "FAKE_TEST_KEY_NOT_VALID_ANYWHERE_1234",
  PRIVI_MAINNET_EVM_CHAIN_ID: "400001",
  PRIVI_MAINNET_EVM_RPC_URL: "https://rpc.privi.example.org",
  PRIVI_EVM_GENESIS_BLOCK_HASH: genesisHash, ...overrides
});
function mockRPC({ cid = "0x61a81", block = "0x30", hash = genesisHash } = {}) {
  return async (_url, options) => {
    const method = JSON.parse(options.body).method;
    const result = method === "eth_chainId" ? cid
      : method === "eth_blockNumber" ? block
      : method === "eth_getBlockByNumber" ? { hash } : null;
    return { ok:true, async json() { return { jsonrpc:"2.0", id:1, result }; } };
  };
}
function signed(body=raw, timestamp=NOW, nonce="0123456789abcdef0123456789abcdef") {
  const reqHeaders = signedHeaders(fakeSecret, {
    route, origin: trusted, userId, body, now: timestamp, nonce
  });
  const out = {};
  for (const [k, v] of Object.entries(reqHeaders)) out[k.toLowerCase()] = v;
  return out;
}
function verify(headers, body=raw, replayCache = new NonceCache(), now=NOW) {
  return verifyRequest({
    key:fakeSecret, headers, route, rawBody:body,
    allowedOrigins:new Set([trusted]), replayCache, now
  });
}
function siteEnv() {
  return {
    MR_LEE_WEBSITE_ORIGIN:trusted,
    MR_LEE_PRIVATE_GATEWAY_URL:"https://private-gateway.example.org",
    MR_LEE_GATEWAY_TOKEN:fakeSecret
  };
}
function siteRequest({
  origin=trusted, site="same-origin", csrf="valid-csrf", body=raw,
  path="/api/mr-lee/chat", contentType="application/json"
} = {}) {
  return new Request(trusted + path, {
    method:"POST",
    headers: {
      "origin":origin, "sec-fetch-site":site,
      "content-type":contentType, "x-csrf-token":csrf
    },
    body
  });
}
function session(changes={}) {
  return { userId, active:true, mfaVerified:true, authTimeMs:NOW-1000, ...changes };
}
function siteHandler(overrides={}) {
  return makeMrLeeWebsiteHandler({
    env:siteEnv(), now:()=>NOW,
    getAuthenticatedSession:async ()=>session(),
    verifyCsrf:async req=>req.headers.get("x-csrf-token")==="valid-csrf",
    fetchImpl:async () => ({ status:200, async text(){return '{"reply":"Hi"}';} }),
    ...overrides
  });
}

test("Mr. Lee is strictly disabled by default", () => {
  const cfg=getConfig({});
  assert.equal(cfg.enabled,false);
});

test("TEST, BNB, synthetic chains and unverified genesis block activation", () => {
  for (const id of [1,56,97,1337,4221,31337,262144,999991,2026101601]) {
    assert.throws(()=>getConfig(createEnv({PRIVI_MAINNET_EVM_CHAIN_ID:String(id)})));
  }
  assert.throws(()=>getConfig(createEnv({PRIVI_EVM_GENESIS_BLOCK_HASH:""})));
  assert.throws(()=>getConfig(createEnv({PRIVI_MAINNET_EVM_RPC_URL:"http://127.0.0.1:26657"})));
  assert.throws(()=>getConfig(createEnv({MR_LEE_ALLOWED_ORIGINS:"*"})));
  assert.throws(()=>getConfig(createEnv({OPENAI_API_KEY:""})));
  assert.throws(()=>getConfig(createEnv({MR_LEE_GATEWAY_TOKEN:""})));
});

test("HMAC signs method/route/origin/user/nonce/timestamp and exact body", () => {
  const headers=signed();
  assert.ok(verify(headers));
  assert.equal(verify(headers,raw+" "),false);
  assert.equal(verify({...headers,"x-privi-user-id":"otheruser123"}),false);
  assert.equal(verify({...headers,"x-privi-website-origin":"https://evil.example"}),false);
  assert.equal(verify({...headers,"x-privi-signature":"v1="+"0".repeat(64)}),false);
  assert.equal(verify({...headers, origin:trusted}),false);
  assert.equal(verify({...headers, cookie:"sid=attacker"}),false);
  assert.equal(verify({...headers,"x-privi-nonce":"0".repeat(32)}),false);
  assert.equal(verify(headers,raw,new NonceCache(),NOW+61_000),false);
  assert.equal(verify(headers,raw,new NonceCache(),NOW-61_000),false);
  assert.equal(verify(headers,raw,new NonceCache(),NOW),true);
  assert.equal(verifyRequest({
    key:fakeSecret,headers,route:"/internal/mr-lee/paper-trade",
    rawBody:raw,allowedOrigins:new Set([trusted]),
    replayCache:new NonceCache(),now:NOW
  }),false);
});

test("HMAC signed requests cannot be replayed", () => {
  const cache=new NonceCache(), h=signed();
  assert.equal(verify(h,raw,cache),true);
  assert.equal(verify(h,raw,cache),false);
  assert.equal(verify(signed(raw,NOW,"1234567890abcdef1234567890abcdef"),raw,cache),true);
});

test("screen out common seed phrases, API keys, private keys", () => {
  assert.equal(containsCredentialLikeText("Help with staking"),false);
  assert.equal(containsCredentialLikeText("password=secretsecretsecret"),true);
  assert.equal(containsCredentialLikeText("api_key: abcdefghijklmnopqrstuv"),true);
  assert.equal(containsCredentialLikeText("-----BEGIN PRIVATE KEY-----"),true);
});

test("server-side RPC verifies exact chain, block production and genesis", async () => {
  const cfg=getConfig(createEnv());
  const net=await checkPriviNetwork(cfg,mockRPC());
  assert.equal(net.ok,true);
  assert.equal(net.height,"48");
  assert.equal((await checkPriviNetwork(cfg,mockRPC({cid:"0x40000"}))).ok,false);
  assert.equal((await checkPriviNetwork(cfg,mockRPC({hash:"0x"+"b".repeat(64)}))).ok,false);
  assert.equal((await checkPriviNetwork(cfg,mockRPC({block:"0x0"}))).ok,false);
  assert.equal((await checkPriviNetwork(cfg,async()=>{throw Error("offline");})).ok,false);
});

test("server-side OpenAI: no tools, no stored responses", async () => {
  const cfg=getConfig(createEnv());
  let request;
  const provider=async (url,options)=>{
    request={url,...options};
    return {ok:true,async json(){return {output:[{
      type:"message",role:"assistant",
      content:[{type:"output_text",text:"Mr. Lee provides PRVI wallet help."}]
    }]};}};
  };
  const result=await askMrLee(cfg,"How does the Privi wallet work?",
    "utility",{chainId:400001,height:"48"},provider);
  assert.match(result,/wallet help/);
  const body=JSON.parse(request.body);
  assert.equal(request.url,"https://api.openai.com/v1/responses");
  assert.equal(body.store,false);
  assert.equal(body.tools,undefined);
  assert.match(body.instructions,/PAPER-TRADE/);
  await assert.rejects(askMrLee(cfg,"x","trade_live",{},provider));
});

test("paper trading cannot execute, quote live prices or sign transfers", () => {
  const q=simulatePaperTrade({symbol:"PRVI/USDC",side:"buy",price:"0.35",quantity:"20"});
  assert.equal(q.notional,"7");
  assert.equal(q.estimated_fee,"0.007");
  assert.equal(q.executed,false);
  assert.equal(q.quote_is_live,false);
  assert.throws(()=>simulatePaperTrade({symbol:"PRVI/USDC",side:"withdraw",price:"1",quantity:"5"}));
});

test("Privi website requires real session verifier AND real CSRF verifier", () => {
  assert.throws(()=>makeMrLeeWebsiteHandler({getAuthenticatedSession:()=>null}));
  assert.throws(()=>makeMrLeeWebsiteHandler({
    getAuthenticatedSession:()=>session(),env:siteEnv()
  }));
});

test("website rejects cross-origin, cross-site requests and missing CSRF", async () => {
  const handler=siteHandler();
  assert.equal((await handler(siteRequest({origin:"https://evil.example"}))).status,403);
  assert.equal((await handler(siteRequest({site:"cross-site"}))).status,403);
  assert.equal((await handler(siteRequest({site:"none"}))).status,403);
  assert.equal((await handler(siteRequest({csrf:"wrong"}))).status,403);
  assert.equal((await handler(siteRequest({contentType:"text/plain"}))).status,403);
  assert.equal((await handler(siteRequest({path:"/api/mr-lee/not-allowed"}))).status,404);
});

test("website rejects anonymous, single-factor, expired or revoked sessions", async () => {
  for (const state of [null,session({mfaVerified:false}),
       session({active:false}),
       session({authTimeMs:NOW-SESSION_MAX_AGE_MS-1}),
       session({authTimeMs:NOW+100000}),
       session({userId:"bad"})]) {
    const handler=siteHandler({getAuthenticatedSession:async()=>state});
    assert.equal((await handler(siteRequest())).status,403);
  }
});

test("website forwards HMAC-signed, timestamped request WITHOUT sharing secret", async () => {
  let forwarded;
  const handler=siteHandler({
    fetchImpl:async (url,req)=>{
      forwarded={url,...req};
      return {status:200,async text(){return '{"reply":"Welcome"}';}};
    }
  });
  const res=await handler(siteRequest());
  assert.equal(res.status,200);
  assert.equal(forwarded.url,"https://private-gateway.example.org/internal/mr-lee/chat");
  assert.equal(forwarded.headers.Authorization,undefined);
  assert.equal(forwarded.headers["X-Privi-User-Id"],userId);
  const h={};
  for(const [k,v] of Object.entries(forwarded.headers))h[k.toLowerCase()]=v;
  assert.equal(verify(h,raw,new NonceCache(),NOW),true);
  assert.equal(res.headers.get("cache-control"),"no-store, max-age=0");
});
