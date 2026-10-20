import http from 'http';
import { readFileSync, existsSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import crypto from 'crypto';
import { db } from './store.js';
import { hashPassword, verifyPassword, encryptSecret, decryptSecret, randomToken } from './crypto-utils.js';
import { plugins, getPlugin } from './plugins/index.js';
import { config, publicConfig, paymentsConfigured } from './config.js';
import { askJose, sanitizeHistory } from './ai.js';
import {
  recoverPersonalSign, isAddress, sameAddress, erc20TransferredInTx, erc721OwnerOf, erc721TokenURI,
} from './eth.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, '../public');
const PORT = process.env.PORT || 7000;
const BASE_URL = process.env.BASE_URL || `http://localhost:${PORT}`;
const SESSION_COOKIE = 'jose_session';
const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000; // 30 days

// Short-lived store for OAuth `state` values, so the callback can be tied
// back to the user who started the connect flow and we can reject replay /
// CSRF attempts. In-memory is fine: a connect flow finishes in minutes.
const pendingOAuth = new Map();

// Wallet-link challenges: userId -> { message, expiresAt }. A user proves they
// control a wallet by signing this exact message in MetaMask.
const pendingWalletLinks = new Map();
const WALLET_CHALLENGE_TTL_MS = 10 * 60 * 1000;
const MAX_BODY_BYTES = 200 * 1024;

function sendJson(res, status, obj) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(obj));
}

function sendFile(res, filePath) {
  if (!existsSync(filePath)) {
    res.writeHead(404);
    res.end('Not found');
    return;
  }
  const ext = path.extname(filePath);
  const type = {
    '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'application/javascript',
    '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json',
  }[ext] || 'application/octet-stream';
  res.writeHead(200, { 'Content-Type': type });
  res.end(readFileSync(filePath));
}

function parseCookies(req) {
  const header = req.headers.cookie || '';
  return Object.fromEntries(
    header.split(';').filter(Boolean).map((p) => {
      const [k, ...v] = p.trim().split('=');
      return [k, decodeURIComponent(v.join('='))];
    })
  );
}

function getCurrentUser(req) {
  const cookies = parseCookies(req);
  const token = cookies[SESSION_COOKIE];
  if (!token) return null;
  const session = db.getSession(token);
  if (!session || session.expiresAt < Date.now()) return null;
  const user = db.getUser(session.userId);
  // Accounts created before v3 have no credit balance yet: give them the
  // same one-time starter credits new signups get.
  if (user && user.credits === undefined) db.updateUser(user.id, { credits: config.freeCredits });
  return user;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => {
      data += c;
      if (data.length > MAX_BODY_BYTES) {
        reject(Object.assign(new Error('Request body too large.'), { status: 413 }));
        req.destroy();
      }
    });
    req.on('end', () => {
      try {
        resolve(data ? JSON.parse(data) : {});
      } catch (e) {
        reject(e);
      }
    });
    req.on('error', reject);
  });
}

function publicPluginList(user) {
  return plugins.map((p) => {
    const connection = user ? db.getConnection(user.id, p.id) : null;
    return {
      id: p.id,
      name: p.name,
      configured: p.isConfigured(),
      missingEnvVars: p.isConfigured() ? [] : p.missingEnvVars(),
      connected: Boolean(connection),
      connectedAt: connection ? connection.connectedAt : null,
      setup: p.setup,
      redirectUri: `${BASE_URL}/callback/${p.id}`,
    };
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, BASE_URL);

  try {
    // ---- auth ----
    if (req.method === 'POST' && url.pathname === '/api/signup') {
      const { email, password } = await readBody(req);
      if (!email || !password || password.length < 8) {
        return sendJson(res, 400, { error: 'An email and an 8+ character password are required.' });
      }
      if (db.getUserByEmail(email)) {
        return sendJson(res, 409, { error: 'An account with that email already exists.' });
      }
      const user = db.createUser({
        id: crypto.randomUUID(),
        email,
        passwordHash: hashPassword(password),
        createdAt: Date.now(),
        credits: config.freeCredits,
        wallet: null,
      });
      const token = randomToken();
      db.createSession({ token, userId: user.id, expiresAt: Date.now() + SESSION_TTL_MS });
      res.setHeader('Set-Cookie', `${SESSION_COOKIE}=${token}; HttpOnly; Path=/; Max-Age=${SESSION_TTL_MS / 1000}`);
      return sendJson(res, 201, { email: user.email });
    }

    if (req.method === 'POST' && url.pathname === '/api/login') {
      const { email, password } = await readBody(req);
      const user = db.getUserByEmail(email || '');
      if (!user || !verifyPassword(password || '', user.passwordHash)) {
        return sendJson(res, 401, { error: 'Incorrect email or password.' });
      }
      const token = randomToken();
      db.createSession({ token, userId: user.id, expiresAt: Date.now() + SESSION_TTL_MS });
      res.setHeader('Set-Cookie', `${SESSION_COOKIE}=${token}; HttpOnly; Path=/; Max-Age=${SESSION_TTL_MS / 1000}`);
      return sendJson(res, 200, { email: user.email });
    }

    if (req.method === 'POST' && url.pathname === '/api/logout') {
      const cookies = parseCookies(req);
      if (cookies[SESSION_COOKIE]) db.deleteSession(cookies[SESSION_COOKIE]);
      res.setHeader('Set-Cookie', `${SESSION_COOKIE}=; HttpOnly; Path=/; Max-Age=0`);
      return sendJson(res, 200, { ok: true });
    }

    if (req.method === 'GET' && url.pathname === '/api/me') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Not signed in.' });
      return sendJson(res, 200, {
        email: user.email,
        wallet: user.wallet || null,
        credits: user.credits || 0,
        plugins: publicPluginList(user),
      });
    }

    // ---- v3: public config (chain, token, payments, AI on/off) ----
    if (req.method === 'GET' && url.pathname === '/api/config') {
      // Public values only, no cookies: safe for the jose-site to read.
      res.setHeader('Access-Control-Allow-Origin', '*');
      return sendJson(res, 200, publicConfig());
    }

    // ---- v3: link a MetaMask wallet to the account (signed challenge) ----
    if (req.method === 'POST' && url.pathname === '/api/wallet/challenge') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Not signed in.' });
      const { address } = await readBody(req);
      if (!isAddress(address)) return sendJson(res, 400, { error: 'A valid wallet address is required.' });
      const message =
        `Link this wallet to my Jose account.\n\n` +
        `Account: ${user.email}\nWallet: ${address.toLowerCase()}\n` +
        `Nonce: ${randomToken(12)}\nIssued: ${new Date().toISOString()}\n\n` +
        `Signing this costs nothing and does not send a transaction.`;
      pendingWalletLinks.set(user.id, { message, address: address.toLowerCase(), expiresAt: Date.now() + WALLET_CHALLENGE_TTL_MS });
      return sendJson(res, 200, { message });
    }

    if (req.method === 'POST' && url.pathname === '/api/wallet/link') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Not signed in.' });
      const { signature } = await readBody(req);
      const pending = pendingWalletLinks.get(user.id);
      if (!pending || pending.expiresAt < Date.now()) {
        return sendJson(res, 400, { error: 'That request expired. Try linking again.' });
      }
      let signer;
      try {
        signer = recoverPersonalSign(pending.message, signature);
      } catch {
        return sendJson(res, 400, { error: 'Could not read that signature.' });
      }
      if (!sameAddress(signer, pending.address)) {
        return sendJson(res, 400, { error: 'The signature does not match that wallet.' });
      }
      const other = db.getUserByWallet(signer);
      if (other && other.id !== user.id) {
        return sendJson(res, 409, { error: 'That wallet is already linked to another Jose account.' });
      }
      pendingWalletLinks.delete(user.id);
      db.updateUser(user.id, { wallet: signer, walletLinkedAt: Date.now() });
      return sendJson(res, 200, { wallet: signer });
    }

    if (req.method === 'POST' && url.pathname === '/api/wallet/unlink') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Not signed in.' });
      db.updateUser(user.id, { wallet: null, walletLinkedAt: null });
      return sendJson(res, 200, { ok: true });
    }

    // ---- v3: AI credits, paid in JOSE ----
    if (req.method === 'GET' && url.pathname === '/api/credits') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Not signed in.' });
      return sendJson(res, 200, {
        credits: db.getUser(user.id).credits || 0,
        payments: db.getPaymentsForUser(user.id).map(({ txHash, amount, credits, claimedAt }) => ({ txHash, amount, credits, claimedAt })),
      });
    }

    if (req.method === 'POST' && url.pathname === '/api/credits/claim') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Not signed in.' });
      if (!paymentsConfigured()) {
        return sendJson(res, 503, { error: 'Paying with JOSE is not switched on for this server yet.' });
      }
      if (!user.wallet) return sendJson(res, 400, { error: 'Link your wallet first, then pay from that wallet.' });
      const { txHash } = await readBody(req);
      if (!/^0x[0-9a-fA-F]{64}$/.test(String(txHash || ''))) {
        return sendJson(res, 400, { error: 'That does not look like a transaction hash.' });
      }
      if (db.getPayment(txHash)) return sendJson(res, 409, { error: 'That payment was already claimed.' });

      let result;
      try {
        result = await erc20TransferredInTx(config.rpcUrl, txHash, {
          token: config.tokenAddress, from: user.wallet, to: config.treasuryAddress,
        });
      } catch (err) {
        return sendJson(res, 502, { error: 'Could not reach the network to check that payment. Try again shortly.' });
      }
      if (!result.found) return sendJson(res, 404, { error: 'Transaction not found yet. Wait for it to confirm and try again.' });
      if (result.failed) return sendJson(res, 400, { error: 'That transaction failed on-chain.' });
      if (result.amount === 0n) {
        return sendJson(res, 400, { error: `No ${config.tokenSymbol} transfer from your linked wallet to the Jose treasury in that transaction.` });
      }
      if (result.confirmations < config.minConfirmations) {
        return sendJson(res, 425, { error: `Waiting for confirmations (${result.confirmations}/${config.minConfirmations}). Try again in a minute.` });
      }
      const unit = 10n ** BigInt(config.tokenDecimals);
      const perCredit = BigInt(Math.round(config.josePerCredit * 1e6)) * unit / 1000000n;
      const credits = Number(result.amount / perCredit);
      if (credits < 1) {
        return sendJson(res, 400, { error: `That payment is less than the price of one credit (${config.josePerCredit} ${config.tokenSymbol}).` });
      }
      // Re-check right before writing, in case two claims raced.
      if (db.getPayment(txHash)) return sendJson(res, 409, { error: 'That payment was already claimed.' });
      db.recordPayment({ txHash, userId: user.id, wallet: user.wallet, amount: result.amount.toString(), credits, claimedAt: Date.now() });
      const balance = db.addCredits(user.id, credits);
      return sendJson(res, 200, { added: credits, credits: balance });
    }

    // ---- v3: Hey Jose chat ----
    if (req.method === 'POST' && url.pathname === '/api/chat') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Sign in to chat with Jose.' });
      if (!config.anthropicApiKey) return sendJson(res, 503, { error: 'Hey Jose is not switched on for this server yet.' });
      const { messages } = await readBody(req);
      const history = sanitizeHistory(messages);
      if (!history) return sendJson(res, 400, { error: 'Send at least one message.' });
      const cost = config.creditsPerMessage;
      if (!db.spendCredits(user.id, cost)) {
        return sendJson(res, 402, { error: 'You are out of credits.', credits: db.getUser(user.id).credits || 0 });
      }
      try {
        const reply = await askJose(history);
        return sendJson(res, 200, { reply, credits: db.getUser(user.id).credits });
      } catch (err) {
        db.addCredits(user.id, cost); // don't charge for a failed answer
        return sendJson(res, err.status || 502, { error: err.message, credits: db.getUser(user.id).credits });
      }
    }

    // ---- v3: NFT marketplace (listings) ----
    if (req.method === 'GET' && url.pathname === '/api/nfts') {
      const seller = url.searchParams.get('seller');
      return sendJson(res, 200, { listings: db.listListings({ seller: isAddress(seller) ? seller : undefined }) });
    }

    const nftMatch = url.pathname.match(/^\/api\/nfts\/([a-f0-9-]{36})(\/cancel)?$/);
    if (req.method === 'GET' && nftMatch && !nftMatch[2]) {
      const listing = db.getListing(nftMatch[1]);
      if (!listing) return sendJson(res, 404, { error: 'Listing not found.' });
      // If the seller no longer holds the NFT, the listing is stale.
      if (listing.status === 'active') {
        try {
          const owner = await erc721OwnerOf(config.rpcUrl, listing.contract, listing.tokenId);
          if (!sameAddress(owner, listing.seller)) db.updateListing(listing.id, { status: 'stale' });
        } catch { /* network hiccup: show the listing as-is */ }
      }
      return sendJson(res, 200, { listing: db.getListing(listing.id) });
    }

    if (req.method === 'POST' && nftMatch && nftMatch[2]) {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Not signed in.' });
      const listing = db.getListing(nftMatch[1]);
      if (!listing) return sendJson(res, 404, { error: 'Listing not found.' });
      if (listing.userId !== user.id) return sendJson(res, 403, { error: 'Only the seller can remove this listing.' });
      db.updateListing(listing.id, { status: 'cancelled', cancelledAt: Date.now() });
      return sendJson(res, 200, { ok: true });
    }

    if (req.method === 'POST' && url.pathname === '/api/nfts') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Not signed in.' });
      if (!user.wallet) return sendJson(res, 400, { error: 'Link your wallet first — listings are tied to the wallet that holds the NFT.' });
      const body = await readBody(req);
      const contract = String(body.contract || '').trim();
      const tokenId = String(body.tokenId || '').trim();
      const price = Number(body.price);
      const title = String(body.title || '').trim().slice(0, 80);
      const description = String(body.description || '').trim().slice(0, 1000);
      if (!isAddress(contract)) return sendJson(res, 400, { error: 'Enter the NFT contract address (0x…).' });
      if (!/^\d{1,78}$/.test(tokenId)) return sendJson(res, 400, { error: 'Enter the token ID (a whole number).' });
      if (!Number.isFinite(price) || price <= 0 || price > 1e12) return sendJson(res, 400, { error: `Enter a price in ${config.tokenSymbol} greater than 0.` });
      if (db.findActiveListing(contract, tokenId)) return sendJson(res, 409, { error: 'That NFT is already listed.' });

      let owner;
      try {
        owner = await erc721OwnerOf(config.rpcUrl, contract, tokenId);
      } catch {
        return sendJson(res, 400, { error: `Could not find that NFT on ${config.chainName}. Check the contract address and token ID.` });
      }
      if (!sameAddress(owner, user.wallet)) {
        return sendJson(res, 403, { error: 'Your linked wallet does not hold that NFT.' });
      }
      const tokenURI = await erc721TokenURI(config.rpcUrl, contract, tokenId);
      const listing = db.createListing({
        id: crypto.randomUUID(),
        userId: user.id,
        seller: user.wallet,
        contract,
        tokenId,
        tokenURI: tokenURI.slice(0, 2000),
        price,
        currency: config.tokenSymbol,
        title,
        description,
        chainId: config.chainId,
        status: 'active',
        createdAt: Date.now(),
      });
      return sendJson(res, 201, { listing });
    }

    // ---- plugin connect / callback (real OAuth, per plugins/*.js) ----
    if (req.method === 'GET' && url.pathname.startsWith('/connect/')) {
      const user = getCurrentUser(req);
      if (!user) {
        res.writeHead(302, { Location: '/login.html?next=' + encodeURIComponent(url.pathname) });
        return res.end();
      }
      const pluginId = url.pathname.split('/')[2];
      const plugin = getPlugin(pluginId);
      if (!plugin) return sendJson(res, 404, { error: 'Unknown plugin.' });
      if (!plugin.isConfigured()) {
        return sendJson(res, 503, {
          error: `${plugin.name} isn't configured on this server yet.`,
          missingEnvVars: plugin.missingEnvVars(),
        });
      }
      const state = randomToken(16);
      pendingOAuth.set(state, { userId: user.id, pluginId, createdAt: Date.now() });
      const redirectUri = `${BASE_URL}/callback/${pluginId}`;
      const authorizeUrl = plugin.buildAuthorizeUrl(state, redirectUri);
      res.writeHead(302, { Location: authorizeUrl });
      return res.end();
    }

    if (req.method === 'GET' && url.pathname.startsWith('/callback/')) {
      const pluginId = url.pathname.split('/')[2];
      const plugin = getPlugin(pluginId);
      const code = url.searchParams.get('code');
      const state = url.searchParams.get('state');
      const pending = state && pendingOAuth.get(state);

      if (!plugin || !code || !pending || pending.pluginId !== pluginId) {
        res.writeHead(302, { Location: '/dashboard.html?error=invalid_oauth_state' });
        return res.end();
      }
      pendingOAuth.delete(state);

      try {
        const redirectUri = `${BASE_URL}/callback/${pluginId}`;
        const result = await plugin.exchangeCode(code, redirectUri);
        db.setConnection(pending.userId, pluginId, {
          connectedAt: Date.now(),
          accessTokenEnc: encryptSecret(result.accessToken),
          refreshTokenEnc: result.refreshToken ? encryptSecret(result.refreshToken) : null,
          expiresInSeconds: result.expiresInSeconds || null,
        });
        res.writeHead(302, { Location: '/dashboard.html?connected=' + pluginId });
        return res.end();
      } catch (err) {
        res.writeHead(302, { Location: '/dashboard.html?error=' + encodeURIComponent(err.message) });
        return res.end();
      }
    }

    if (req.method === 'POST' && url.pathname.startsWith('/api/disconnect/')) {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Not signed in.' });
      const pluginId = url.pathname.split('/')[3];
      db.removeConnection(user.id, pluginId);
      return sendJson(res, 200, { ok: true });
    }

    // ---- static files ----
    if (req.method === 'GET') {
      const filePath = url.pathname === '/' ? '/dashboard.html' : url.pathname;
      const full = path.join(PUBLIC_DIR, filePath);
      if (!full.startsWith(PUBLIC_DIR)) return sendJson(res, 403, { error: 'forbidden' });
      return sendFile(res, full);
    }

    return sendJson(res, 404, { error: 'not found' });
  } catch (err) {
    if (err instanceof SyntaxError) return sendJson(res, 400, { error: 'Invalid JSON.' });
    if (err.status === 413) return sendJson(res, 413, { error: err.message });
    console.error(err);
    return sendJson(res, 500, { error: 'Internal error.' });
  }
});

server.listen(PORT, () => {
  console.log(`Jose backend listening on ${BASE_URL}`);
  console.log(`  Hey Jose AI: ${config.anthropicApiKey ? 'on (' + config.aiModel + ')' : 'off (set ANTHROPIC_API_KEY)'}`);
  console.log(`  JOSE payments: ${paymentsConfigured() ? 'on' : 'off (set JOSE_TOKEN_ADDRESS and JOSE_TREASURY_ADDRESS)'}`);
  for (const p of plugins) {
    console.log(`  ${p.name}: ${p.isConfigured() ? 'configured' : `NOT configured (missing ${p.missingEnvVars().join(', ')})`}`);
  }
});
