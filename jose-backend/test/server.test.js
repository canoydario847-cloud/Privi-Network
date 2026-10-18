// End-to-end test of the v3 routes against a fake Base RPC and a fake AI
// endpoint, both served locally. Runs the real server as a child process.
import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { addressFromPrivateKey, signHash, hashPersonalMessage, TRANSFER_TOPIC } from '../src/eth.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const PRIV = '0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318';
const WALLET = addressFromPrivateKey(PRIV);
const TOKEN = '0x' + '11'.repeat(20);
const TREASURY = '0x' + '22'.repeat(20);
const NFT = '0x' + '33'.repeat(20);
const GOOD_TX = '0x' + 'aa'.repeat(32);
const WRONG_SENDER_TX = '0x' + 'bb'.repeat(32);
const pad32 = (hex) => hex.replace(/^0x/, '').padStart(64, '0');

let rpcServer, aiServer, app, dataDir, base;
let aiCalls = 0;

function listen(server) {
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));
}

function abiString(s) {
  const b = Buffer.from(s, 'utf8');
  return '0x' + pad32('20') + pad32(b.length.toString(16)) + b.toString('hex').padEnd(Math.ceil(b.length / 32) * 64, '0');
}

before(async () => {
  rpcServer = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      const { id, method, params } = JSON.parse(body);
      let result = null;
      if (method === 'eth_blockNumber') result = '0x64';
      if (method === 'eth_call') {
        const data = params[0].data;
        if (data.startsWith('0x6352211e')) result = '0x' + pad32(WALLET); // ownerOf -> our wallet
        if (data.startsWith('0xc87b56dd')) result = abiString('ipfs://QmTest/1.json');
      }
      if (method === 'eth_getTransactionReceipt') {
        const from = params[0] === GOOD_TX ? WALLET : '0x' + '99'.repeat(20);
        if (params[0] === GOOD_TX || params[0] === WRONG_SENDER_TX) {
          result = {
            status: '0x1', blockNumber: '0x5a',
            logs: [{ address: TOKEN, topics: [TRANSFER_TOPIC, '0x' + pad32(from), '0x' + pad32(TREASURY)], data: '0x' + pad32((250n * 10n ** 18n).toString(16)) }],
          };
        }
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ jsonrpc: '2.0', id, result }));
    });
  });
  aiServer = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      aiCalls++;
      const parsed = JSON.parse(body);
      assert.equal(req.headers['x-api-key'], 'test-key');
      assert.ok(parsed.system.includes('Jose'));
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ content: [{ type: 'text', text: 'Hola, soy Jose.' }] }));
    });
  });
  const rpcPort = await listen(rpcServer);
  const aiPort = await listen(aiServer);
  dataDir = mkdtempSync(path.join(tmpdir(), 'jose-test-'));
  const port = 17000 + Math.floor(Math.random() * 1000);
  base = `http://127.0.0.1:${port}`;
  app = spawn(process.execPath, [path.join(here, '../src/server.js')], {
    env: {
      ...process.env, PORT: String(port), BASE_URL: base, APP_SECRET: 'x'.repeat(40),
      DB_FILE: path.join(dataDir, 'db.json'),
      ANTHROPIC_API_KEY: 'test-key', ANTHROPIC_BASE_URL: `http://127.0.0.1:${aiPort}`,
      JOSE_RPC_URL: `http://127.0.0.1:${rpcPort}`, JOSE_TOKEN_ADDRESS: TOKEN, JOSE_TREASURY_ADDRESS: TREASURY,
      JOSE_PER_CREDIT: '5', JOSE_FREE_CREDITS: '2',
    },
    stdio: ['ignore', 'pipe', 'inherit'],
  });
  await new Promise((resolve) => app.stdout.on('data', (d) => d.toString().includes('listening') && resolve()));
});

after(() => {
  app?.kill();
  rpcServer?.close();
  aiServer?.close();
  rmSync(dataDir, { recursive: true, force: true });
});

let cookie = '';
async function call(p, body, method) {
  const res = await fetch(base + p, {
    method: method || (body ? 'POST' : 'GET'),
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(cookie ? { Cookie: cookie } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const setCookie = res.headers.get('set-cookie');
  if (setCookie) cookie = setCookie.split(';')[0];
  return { status: res.status, body: await res.json() };
}

test('v3 flow: config, credits, chat, wallet link, JOSE payment, NFT listing', async () => {
  const cfg = await call('/api/config');
  assert.equal(cfg.body.chain.chainId, 8453);
  assert.equal(cfg.body.chain.chainIdHex, '0x2105');
  assert.equal(cfg.body.token.address, TOKEN);
  assert.equal(cfg.body.payments.enabled, true);
  assert.equal(JSON.stringify(cfg.body).includes('test-key'), false, 'API key must never be exposed');

  assert.equal((await call('/api/chat', { messages: [{ role: 'user', content: 'hola' }] })).status, 401);

  const signup = await call('/api/signup', { email: 'a@b.co', password: 'password123' });
  assert.equal(signup.status, 201);
  let me = await call('/api/me');
  assert.equal(me.body.credits, 2);
  assert.equal(me.body.wallet, null);

  // Chat spends credits, then runs out.
  let chat = await call('/api/chat', { messages: [{ role: 'user', content: 'hola' }] });
  assert.equal(chat.status, 200);
  assert.equal(chat.body.reply, 'Hola, soy Jose.');
  assert.equal(chat.body.credits, 1);
  await call('/api/chat', { messages: [{ role: 'user', content: 'otra' }] });
  chat = await call('/api/chat', { messages: [{ role: 'user', content: 'y otra' }] });
  assert.equal(chat.status, 402);
  assert.equal(aiCalls, 2);
  assert.equal((await call('/api/chat', { messages: [] })).status, 400);

  // Claiming requires a linked wallet.
  assert.equal((await call('/api/credits/claim', { txHash: GOOD_TX })).status, 400);

  // Link wallet: wrong signer is rejected, right signer is accepted.
  const ch = await call('/api/wallet/challenge', { address: WALLET });
  const badSig = signHash(hashPersonalMessage(ch.body.message), '0x' + '01'.padStart(64, '0'));
  assert.equal((await call('/api/wallet/link', { signature: badSig })).status, 400);
  const sig = signHash(hashPersonalMessage(ch.body.message), PRIV);
  const linked = await call('/api/wallet/link', { signature: sig });
  assert.equal(linked.status, 200);
  assert.equal(linked.body.wallet, WALLET);

  // Payment from someone else's wallet doesn't count; ours gives 250/5 = 50.
  assert.equal((await call('/api/credits/claim', { txHash: WRONG_SENDER_TX })).status, 400);
  assert.equal((await call('/api/credits/claim', { txHash: '0x' + 'cc'.repeat(32) })).status, 404);
  const claim = await call('/api/credits/claim', { txHash: GOOD_TX });
  assert.equal(claim.status, 200);
  assert.equal(claim.body.added, 50);
  assert.equal(claim.body.credits, 50);
  assert.equal((await call('/api/credits/claim', { txHash: GOOD_TX })).status, 409, 'no double claim');
  assert.equal((await call('/api/credits')).body.payments.length, 1);

  // NFT listing.
  assert.equal((await call('/api/nfts', { contract: 'nope', tokenId: '1', price: 10 })).status, 400);
  const created = await call('/api/nfts', { contract: NFT, tokenId: '7', price: 120, title: 'Llama de Cusco' });
  assert.equal(created.status, 201);
  assert.equal(created.body.listing.tokenURI, 'ipfs://QmTest/1.json');
  assert.equal((await call('/api/nfts', { contract: NFT, tokenId: '7', price: 1 })).status, 409, 'no duplicate listing');
  const all = await call('/api/nfts');
  assert.equal(all.body.listings.length, 1);
  const one = await call('/api/nfts/' + created.body.listing.id);
  assert.equal(one.body.listing.status, 'active');
  assert.equal((await call(`/api/nfts/${created.body.listing.id}/cancel`, {}, 'POST')).status, 200);
  assert.equal((await call('/api/nfts')).body.listings.length, 0);

  // Pages are served.
  for (const page of ['chat.html', 'market.html', 'nft.html', 'dashboard.html', 'jose-wallet.js']) {
    const r = await fetch(`${base}/${page}`);
    assert.equal(r.status, 200, page);
  }
});
