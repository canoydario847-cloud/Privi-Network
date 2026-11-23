import http from 'http';
import { readFileSync, existsSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import crypto from 'crypto';
import { db } from './store.js';
import { ensureConfiguredAdmin } from './admin-bootstrap.js';
import { hashPassword, verifyPassword, encryptSecret, decryptSecret, randomToken } from './crypto-utils.js';
import { plugins, getPlugin } from './plugins/index.js';
import { createNetworkMonitor } from './network-monitor.js';
import { inferChatMode, normalizeChatMode, maxCompletionTokens, systemPromptFor } from './chat-modes.js';
import { userContentWithAttachments } from './chat-attachments.js';
import { createDevnetClient, devnetQuestion, devnetDetailsQuestion, DEVNET_EVM_ID } from './privi-devnet.js';
import { runJosePower, JOSE_POWERS } from './jose-powers.js';
import { userMemoryMessage } from './chat-memory.js';
import { createGmailClient } from './gmail-client.js';
import { createMailReview } from './gmail-review.js';
import { gmailIntent, gmailConnectionGuide, formatGmailInbox, formatGmailMessage } from './gmail-intents.js';
import {
  REWARD_POLICY, validateRewardReceipt, verifyReceiptSignature, InvalidRewardReceipt,
} from './duration-rewards.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, '../public');
const PORT = process.env.PORT || 7000;
const BASE_URL = process.env.BASE_URL || `http://localhost:${PORT}`;
const SESSION_COOKIE = 'jose_session';
const networkMonitor = createNetworkMonitor();
const devnet = createDevnetClient();
const gmail = createGmailClient({getConnection:(userId,p)=>db.getConnection(userId,p),setConnection:(userId,p,row)=>db.setConnection(userId,p,row),encrypt:encryptSecret,decrypt:decryptSecret});
const mailReview = createMailReview();
ensureConfiguredAdmin();
const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000; // 30 days

// Short-lived store for OAuth `state` values, so the callback can be tied
// back to the user who started the connect flow and we can reject replay /
// CSRF attempts. In-memory is fine: a connect flow finishes in minutes.
const pendingOAuth = new Map();
const chatRate = new Map();
const secureCookie = BASE_URL.startsWith('https:') ? '; Secure' : '';
const authCookie = (token,age) => SESSION_COOKIE+'='+token+'; HttpOnly; SameSite=Lax'+secureCookie+'; Path=/; Max-Age='+age;
function sameOrigin(req){const o=req.headers.origin;return !o || o===new URL(BASE_URL).origin;}
function requireOrigin(req,res){if(sameOrigin(req))return true;sendJson(res,403,{error:'Invalid request origin.'});return false;}

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
  const type = { '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript' }[ext] || 'application/octet-stream';
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
  return db.getUser(session.userId);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => (data += c));
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

async function readLimitedJsonBody(req, maxBytes = 2200000) {
  const declared = Number(req.headers['content-length'] || 0);
  if (declared > maxBytes) throw new RangeError('Chat request exceeds 2.2 MB.');
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    total += chunk.length;
    if (total > maxBytes) throw new RangeError('Chat request exceeds 2.2 MB.');
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

async function readLimitedSignedBody(req) {
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    total += chunk.length;
    if (total > 8192) throw new RangeError('Receipt body exceeds 8 KiB');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
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
    // ---- Jose / Privi monitoring and read-only report card ----
    if (req.method === 'GET' && url.pathname === '/health') {
      return sendJson(res, 200, {
        ok: true, service: 'jose-backend',
        monitor: networkMonitor.getReport().fresh ? 'fresh' : 'pending_or_stale',
      });
    }
    if (req.method === 'GET' && url.pathname === '/api/network/report-card') {
      res.setHeader('Cache-Control', 'no-store');
      return sendJson(res, 200, networkMonitor.getReport());
    }
    if (req.method === 'GET' && url.pathname === '/api/rewards/policy') {
      return sendJson(res, 200, {
        ...REWARD_POLICY,
        signedIssuerConfigured: (process.env.JOSE_REWARD_ISSUER_SECRET || '').length >= 32,
      });
    }
    if (req.method === 'GET' && url.pathname === '/api/rewards/me') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Sign in to view participation points.' });
      return sendJson(res, 200, db.getParticipationBalance('user:' + user.id));
    }
    // Trusted-work-receipt endpoint. No user-controlled heartbeat creates
    // points; only a server-side 32+ character shared-key HMAC work issuer can.
    if (req.method === 'POST' && url.pathname === '/api/rewards/attest') {
      const secret = process.env.JOSE_REWARD_ISSUER_SECRET || '';
      if (secret.length < 32) {
        return sendJson(res, 503, { error: 'Verified rewards issuer is not configured.' });
      }
      let rawBody;
      try {
        rawBody = await readLimitedSignedBody(req);
      } catch (e) {
        return sendJson(res, e instanceof RangeError ? 413 : 400,
          { error: 'Invalid or oversized signed receipt body.' });
      }
      const accepted = verifyReceiptSignature({
        rawBody, timestamp: req.headers['x-privi-timestamp'],
        signature: req.headers['x-privi-signature'], secret,
      });
      if (!accepted) return sendJson(res, 401, { error: 'Invalid or expired issuer signature.' });
      let quote;
      try {
        quote = validateRewardReceipt(JSON.parse(rawBody));
      } catch (e) {
        if (e instanceof SyntaxError || e instanceof InvalidRewardReceipt) {
          return sendJson(res, 400, { error: 'Invalid verified-work receipt.' });
        }
        throw e;
      }
      const health = networkMonitor.getReport();
      if (!health.fresh || health.score < 70) {
        return sendJson(res, 503, {
          error: 'Jose has no sufficiently healthy, current service-health observation.',
        });
      }
      const credited = db.creditParticipation(quote);
      return sendJson(res, credited.duplicate ? 200 : 201, {
        ...credited, proofId: quote.proofId, eligibility: 'ISSUER_SIGNED_WORK_ONLY',
        financialPrviAmount: 0, nativePrviMinted: false,
      });
    }

    // ---- Jose text chat (opt-in configured AI provider, authenticated, bounded) ----
    // Read-only Privi EVM Devnet. Verify remote health + JSON-RPC chain 772626.
    // Never make signing keys, minting, transaction broadcasting or validators
    // available through the chat endpoint.
    if (req.method === 'GET' && url.pathname === '/api/devnet/status') {
      res.setHeader('Cache-Control', 'no-store');
      return sendJson(res, 200, await devnet.check());
    }
    if (req.method === 'GET' && /^\/api\/devnet\/balance\/0x[0-9a-fA-F]{40}$/.test(url.pathname)) {
      try {
        return sendJson(res, 200, await devnet.balance(url.pathname.split('/').at(-1)));
      } catch(error) {
        return sendJson(res, 503, {error:error.message});
      }
    }
    if (req.method === 'GET' && /^\/api\/devnet\/tx\/0x[0-9a-fA-F]{64}$/.test(url.pathname)) {
      try {
        return sendJson(res, 200, await devnet.receipt(url.pathname.split('/').at(-1)));
      } catch(error) {
        return sendJson(res, 503, {error:error.message});
      }
    }
    if (req.method === 'GET' && url.pathname === '/api/chat/status') {
      const user = getCurrentUser(req) || { id: 'guest:' + (req.socket.remoteAddress || 'unknown') };
      return sendJson(res, 200, { available: Boolean(process.env.JOSE_AI_API_KEY), mode: process.env.JOSE_AI_API_KEY ? 'provider' : 'unconfigured', model: process.env.JOSE_AI_API_KEY ? (process.env.JOSE_AI_MODEL || 'gpt-4o-mini') : null, chatModes: ['chat', 'build', 'web3'], priviDevnetExpectedChainId: DEVNET_EVM_ID, priviDevnetStatusUrl: '/api/devnet/status', attachments: ['image/png','image/jpeg','image/webp','text'], maxAttachments: 2, localPowerCount: JOSE_POWERS.length, browserMemorySupported: true, memoryStorage: 'USER_BROWSER_ONLY',gmailConfigured:getPlugin('google').isConfigured(),gmailConnectUrl:'/connect/google' });
    }
    if (req.method === 'POST' && url.pathname === '/api/chat') {
      const user = getCurrentUser(req) || { id: 'guest:' + (req.socket.remoteAddress || 'unknown') };
      // Require same-origin browser requests: cookie sessions must not be callable cross-site.
      const origin = req.headers.origin;
      if (origin && origin !== new URL(BASE_URL).origin) return sendJson(res, 403, { error: 'Invalid request origin.' });
      const apiKey = process.env.JOSE_AI_API_KEY;
      const now = Date.now();
      const bucket = chatRate.get(user.id) || [];
      const recent = bucket.filter(t => now - t < 60_000);
      if (recent.length >= 5) return sendJson(res, 429, { error: 'Please wait a minute before asking more questions.' });
      recent.push(now);
      chatRate.set(user.id, recent);
      let body;
      try { body = await readLimitedJsonBody(req); }
      catch (error) { return sendJson(res, error instanceof RangeError ? 413 : 400, { error: error instanceof RangeError ? 'Chat upload is too large.' : 'Invalid JSON body.' }); }
      if (!body || typeof body !== 'object' || Array.isArray(body)) return sendJson(res, 400, { error: 'Chat request must be a JSON object.' });
      const message = typeof body.message === 'string' ? body.message.trim() : '';
      const mode = body.mode === undefined || body.mode === 'auto'
        ? inferChatMode(message) : normalizeChatMode(body.mode);
      let userContent;
      try { userContent = userContentWithAttachments(message, body.attachments); }
      catch (error) { return sendJson(res, 400, { error: error.message }); }
      if (!message || message.length > 12000) return sendJson(res, 400, { error: 'Enter a question of up to 12,000 characters.' });
      let memoryNote;
      try {memoryNote = userMemoryMessage(body.memories);}
      catch(error){return sendJson(res, 400, {error:error.message});}
      const history = Array.isArray(body.history) ? body.history.slice(-16) : [];
      if (history.some(m => !m || !['user','assistant'].includes(m.role) || typeof m.content !== 'string' || m.content.length > 12000) || history.reduce((n,m)=>n+m.content.length,0)>48000) {
        return sendJson(res, 400, { error: 'Invalid or oversized conversation history.' });
      }
      // Explicit, read-only deterministic local powers run without paid model calls.
      // Never silently discard attachments or claim a tool can see unseen files.
      const localPower = await runJosePower(message);
      if (localPower) {
        if (Array.isArray(body.attachments) && body.attachments.length) {
          return sendJson(res, 400, {error:'Local power commands currently accept pasted text or JSON, not file attachments.'});
        }
        return sendJson(res, 200, {answer:localPower.answer, mode:'chat', power:localPower.power, deterministic:true});
      }
      const mailIntent=gmailIntent(message);
      if(mailIntent){
        const googlePlugin=getPlugin('google');
        const configured=googlePlugin.isConfigured();
        const authenticated=Boolean(user?.id&&!String(user.id).startsWith('guest:'));
        let connected=false;
        if(configured&&authenticated){
          try{gmail.connection(user.id);connected=true;}catch{}
        }
        const setup=gmailConnectionGuide({
          configured,authenticated,connected,
          missingEnvVars:configured?[]:googlePlugin.missingEnvVars()
        });
        // Never ask a general-purpose model to guess whether Gmail is connected.
        // Setup and missing credentials have deterministic, truthful answers.
        if(mailIntent.action==='connect'||!connected){
          return sendJson(res,200,setup);
        }
        try{
          if(mailIntent.action==='inbox'){
            const mailbox=await gmail.inbox(user.id,mailIntent.query);
            return sendJson(res,200,{answer:formatGmailInbox(mailbox),mode:'chat',gmailAction:'inbox',gmail:mailbox});
          }
          if(mailIntent.action==='read'){
            const email=await gmail.read(user.id,mailIntent.id);
            return sendJson(res,200,{answer:formatGmailMessage(email),mode:'chat',gmailAction:'read'});
          }
          if(mailIntent.action==='compose')
            return sendJson(res,200,{answer:'Gmail is connected. Click Gmail in the chat header to open the composer. You can paste a draft or use Jose’s last answer, then review the exact recipient, subject and body before approving Send.',mode:'chat',gmailAction:'compose'});
        }catch(error){return sendJson(res,error.status||502,{error:error.message});}
      }
      if (devnetQuestion(message)) {
        const report = await devnet.check();
        const answer = report.connected
          ? 'Privi Devnet is connected and responding. Verified EVM chain ID: ' + DEVNET_EVM_ID +
            '; Cosmos chain ID: ' + report.cosmosChainId +
            '; latest block: ' + report.latestBlock +
            '; last block age: ' + report.blockAgeSeconds + ' seconds. Gas token: valueless TEST. ' +
            'Explorer: ' + report.rpcUrl + '. Jose runs as an off-chain AI service connected to the devnet; it is not an on-chain AI model, and this is not financial PRVI mainnet.'
          : 'Privi Devnet connection is not verified at the moment. Expected EVM chain ID: ' +
            DEVNET_EVM_ID + '; Cosmos chain ID: privi-devnet-1. ' +
            'The endpoint may be offline, stale, or reporting a different chain. No financial mainnet activity or transaction is implied.';
        return sendJson(res, 200, {answer, mode:'web3', devnet:report});
      }
      let devnetContext = '';
      if (devnetDetailsQuestion(message)) {
        const report=await devnet.check();
        devnetContext = '\nTrusted read-only Privi Devnet observation: ' + JSON.stringify(report) +
          '. If connected=false, do not claim a working live chain. The AI runs off-chain on Render; TEST is valueless. Never offer to sign transactions or invent a transaction receipt.';
      }
      if (!apiKey) return sendJson(res, 503, { error: 'Hey Jose AI is not configured. Add JOSE_AI_API_KEY in the backend service environment to enable real answers. The plugin directory remains separately available.' });
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 60000);
      try {
        const response = await fetch('https://api.openai.com/v1/chat/completions', {
          method: 'POST', signal: controller.signal,
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
          body: JSON.stringify({
            model: process.env.JOSE_AI_MODEL || 'gpt-4o-mini',
            max_completion_tokens: maxCompletionTokens(mode, process.env.JOSE_AI_MAX_TOKENS),
            messages: [
              { role: 'system', content: systemPromptFor(mode) + devnetContext },
              ...(memoryNote ? [memoryNote] : []),
              ...history.map(m => ({ role: m.role, content: m.content })),
              { role: 'user', content: userContent },
            ],
          }),
        });
        if (!response.ok) {
          console.error('Jose AI provider status', response.status);
          if (response.status === 401 || response.status === 403) {
            return sendJson(res, 503, { error: 'Jose AI authentication failed. The operator must replace JOSE_AI_API_KEY with a valid OpenAI API key on Render.' });
          }
          if (response.status === 400) return sendJson(res, 502, { error: 'Hey Jose model configuration was rejected by the AI provider. Check JOSE_AI_MODEL and token settings.' });
          if (response.status === 429) {
            return sendJson(res, 503, { error: 'Jose AI provider is rate-limited or out of API quota. Contact the operator.' });
          }
          return sendJson(res, 502, { error: 'Jose could not get an AI response. Please try again later.' });
        }
        const data = await response.json();
        const answer = data?.choices?.[0]?.message?.content;
        if (typeof answer !== 'string' || !answer.trim()) return sendJson(res, 502, { error: 'The AI provider returned no answer.' });
        return sendJson(res, 200, { answer: answer.trim(), mode });
      } catch (error) {
        console.error('Jose AI request failed', error?.name);
        return sendJson(res, 504, { error: 'Jose timed out while answering. Try again.' });
      } finally { clearTimeout(timeout); }
    }

    // ---- Gmail API: account-bound, read-only queries and exact preview-before-send ----
    if (url.pathname.startsWith('/api/gmail/') || url.pathname==='/api/email/send') {
      const user=getCurrentUser(req);
      if(!user)return sendJson(res,401,{error:'Sign in to Jose to use your Gmail account.'});
      if(!getPlugin('google').isConfigured())
        return sendJson(res,503,{error:'Gmail needs OAuth configuration by Jose operator: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and APP_SECRET.'});
      if(req.method!=='GET'&&!requireOrigin(req,res))return;
      if(url.pathname==='/api/email/send')return sendJson(res,410,{error:'Use /api/gmail/prepare and /api/gmail/send with a one-use user-confirmed review token.'});
      if(req.method==='GET'&&url.pathname==='/api/gmail/status'){
        let connected=false;
        try{gmail.connection(user.id);connected=true;}catch{}
        return sendJson(res,200,{connected,configured:true,scopes:['gmail.readonly','gmail.send'],email:user.email,
          storage:'Current backend account store (not durable on Render free service)',reviewRequired:true});
      }
      try{
        if(req.method==='GET'&&url.pathname==='/api/gmail/inbox'){
          const data=await gmail.inbox(user.id,url.searchParams.get('q')||'');
          return sendJson(res,200,data);
        }
        const read=url.pathname.match(/^\/api\/gmail\/message\/([A-Za-z0-9]{8,50})$/);
        if(req.method==='GET'&&read)return sendJson(res,200,await gmail.read(user.id,read[1]));
        if(req.method==='POST'&&url.pathname==='/api/gmail/prepare'){
          const body=await readLimitedJsonBody(req,30000);
          gmail.connection(user.id);
          return sendJson(res,200,mailReview.prepare(user.id,body));
        }
        if(req.method==='POST'&&url.pathname==='/api/gmail/send'){
          const body=await readLimitedJsonBody(req,1000);
          gmail.connection(user.id);
          const draft=mailReview.consume(user.id,body.reviewToken,body.confirmSend);
          // The one-time token is consumed before calling Gmail to avoid duplicate retries.
          try{return sendJson(res,200,{ok:true,provider:'gmail',...await gmail.send(user.id,draft)});}
          catch(error){return sendJson(res,502,{error:'Gmail send may have failed. Check Sent Mail before preparing a new message; do not retry this send token.'});}
        }
        return sendJson(res,404,{error:'Unknown Gmail endpoint.'});
      }catch(error){
        return sendJson(res,error instanceof SyntaxError?400:error instanceof RangeError?413:(error.status||400),
          {error:error.message||'Gmail operation failed.'});
      }
    }

    // ---- social sign-in ----
    if (req.method === 'GET' && (url.pathname === '/auth/github' || url.pathname === '/auth/google')) {
      const provider = url.pathname.split('/')[2];
      const configured = provider === 'github'
        ? Boolean(process.env.GITHUB_CLIENT_ID && process.env.GITHUB_CLIENT_SECRET)
        : Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET);
      if (!configured) {
        return sendJson(res, 503, { error: provider + ' sign-in is not configured on this service yet. Add the provider OAuth credentials in Render environment variables.' });
      }
      return sendJson(res, 501, { error: provider + ' OAuth callback is not enabled in this release.' });
    }

    // ---- auth ----
    if (req.method === 'POST' && url.pathname === '/api/signup') {
      if(!requireOrigin(req,res))return;
      const { email: rawEmail, password } = await readLimitedJsonBody(req,10000);
      const email=typeof rawEmail==='string'?rawEmail.trim().toLowerCase():'';
      if (!/^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$/.test(email) || typeof password!=='string' || password.length < 8 || password.length>256) {
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
      });
      const token = randomToken();
      db.createSession({ token, userId: user.id, expiresAt: Date.now() + SESSION_TTL_MS });
      res.setHeader('Set-Cookie', authCookie(token,SESSION_TTL_MS / 1000));
      return sendJson(res, 201, { email: user.email });
    }

    if (req.method === 'POST' && url.pathname === '/api/login') {
      if(!requireOrigin(req,res))return;
      const { email, password } = await readLimitedJsonBody(req,10000);
      const user = db.getUserByEmail(String(email || '').trim().toLowerCase());
      if (!user || !verifyPassword(password || '', user.passwordHash)) {
        return sendJson(res, 401, { error: 'Incorrect email or password.' });
      }
      const token = randomToken();
      db.createSession({ token, userId: user.id, expiresAt: Date.now() + SESSION_TTL_MS });
      res.setHeader('Set-Cookie', authCookie(token,SESSION_TTL_MS / 1000));
      return sendJson(res, 200, { email: user.email });
    }

    if (req.method === 'POST' && url.pathname === '/api/logout') {
      if(!requireOrigin(req,res))return;
      const cookies = parseCookies(req);
      if (cookies[SESSION_COOKIE]) db.deleteSession(cookies[SESSION_COOKIE]);
      res.setHeader('Set-Cookie', authCookie('',0));
      return sendJson(res, 200, { ok: true });
    }

    if (req.method === 'GET' && url.pathname === '/api/me') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Not signed in.' });
      return sendJson(res, 200, { email: user.email, plugins: publicPluginList(user) });
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
      const currentUser=getCurrentUser(req);

      if (!plugin || !code || !pending || pending.pluginId !== pluginId ||
          !currentUser || currentUser.id!==pending.userId || Date.now()-pending.createdAt>600000) {
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
          expiresAt: Date.now() + (result.expiresInSeconds||3600)*1000,
          scopes: result.scopes || [],
        });
        res.writeHead(302, { Location: pluginId==='google'?'/chat.html?gmail=connected':'/dashboard.html?connected='+pluginId });
        return res.end();
      } catch (err) {
        res.writeHead(302, { Location: pluginId==='google'?'/chat.html?gmail=error':'/dashboard.html?error=connection_failed' });
        return res.end();
      }
    }

    if (req.method === 'POST' && url.pathname.startsWith('/api/disconnect/')) {
      if(!requireOrigin(req,res))return;
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
    console.error(err);
    return sendJson(res, 500, { error: 'Internal error.' });
  }
});

server.listen(PORT, () => {
  networkMonitor.start();
  console.log(`Jose backend listening on ${BASE_URL}`);
  for (const p of plugins) {
    console.log(`  ${p.name}: ${p.isConfigured() ? 'configured' : `NOT configured (missing ${p.missingEnvVars().join(', ')})`}`);
  }
});
