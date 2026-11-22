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
import {
  REWARD_POLICY, validateRewardReceipt, verifyReceiptSignature, InvalidRewardReceipt,
} from './duration-rewards.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, '../public');
const PORT = process.env.PORT || 7000;
const BASE_URL = process.env.BASE_URL || `http://localhost:${PORT}`;
const SESSION_COOKIE = 'jose_session';
const networkMonitor = createNetworkMonitor();
ensureConfiguredAdmin();
const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000; // 30 days

// Short-lived store for OAuth `state` values, so the callback can be tied
// back to the user who started the connect flow and we can reject replay /
// CSRF attempts. In-memory is fine: a connect flow finishes in minutes.
const pendingOAuth = new Map();
const chatRate = new Map();

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
    if (req.method === 'GET' && url.pathname === '/api/chat/status') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Sign in to chat with Jose.' });
      return sendJson(res, 200, { available: Boolean(process.env.JOSE_AI_API_KEY), model: process.env.JOSE_AI_MODEL || 'gpt-4o-mini' });
    }
    if (req.method === 'POST' && url.pathname === '/api/chat') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Sign in to chat with Jose.' });
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
      try { body = await readBody(req); }
      catch { return sendJson(res, 400, { error: 'Invalid JSON body.' }); }
      const message = typeof body.message === 'string' ? body.message.trim() : '';
      if (!message || message.length > 2000) return sendJson(res, 400, { error: 'Enter a question of up to 2,000 characters.' });
      const localAnswer = (text) => {
        const q = text.toLowerCase();
        const spanish = /\b(hola|que|qué|como|cómo|precio|precios|ayuda|herramientas)\b/.test(q);
        if (/\b(price|pricing|precio|precios|cost|costo)\b/.test(q)) {
          return spanish ? 'Hey Jose ofrece 500 preguntas y respuestas por $10 al mes, o 1,000 preguntas y respuestas por $35 al mes con acceso a los 85 plugins.' : 'Hey Jose offers 500 questions and answers for $10 per month, or 1,000 questions and answers for $35 per month with access to all 85 plugins.';
        }
        if (/\b(plugin|plugins|tool|tools|herramienta|herramientas)\b/.test(q)) {
          return spanish ? 'Abre Explorar plugins para añadir las herramientas de Privi a tu espacio. Cada plugin conserva sus propios requisitos de acceso.' : 'Open Explore plugins to add Privi capabilities to your workspace. Each plugin keeps its own access requirements.';
        }
        if (/\b(hello|hi|hola|hey)\b/.test(q)) {
          return spanish ? 'Hola. Soy Hey Jose. Puedo ayudarte con los plugins de Privi, tus preguntas y el espacio de trabajo.' : 'Hello. I am Hey Jose. I can help with Privi plugins, questions, and your workspace.';
        }
        return spanish ? 'Puedo ayudarte con precios, plugins y el espacio de Hey Jose. Para respuestas generales, configura el proveedor de IA del servicio.' : 'I can help with pricing, plugins, and the Hey Jose workspace. For general questions, configure the service AI provider.';
      };
      if (!apiKey) return sendJson(res, 200, { answer: localAnswer(message) });
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 20000);
      try {
        const response = await fetch('https://api.openai.com/v1/chat/completions', {
          method: 'POST', signal: controller.signal,
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
          body: JSON.stringify({
            model: process.env.JOSE_AI_MODEL || 'gpt-4o-mini',
            max_tokens: 500,
            messages: [
              { role: 'system', content: 'You are Hey Jose, a helpful Privi assistant. Respond in the same language as the user (English, Spanish, Portuguese or Chinese). Be accurate, concise, and admit uncertainty. Do not claim you took actions or accessed private accounts.' },
              { role: 'user', content: message },
            ],
          }),
        });
        if (!response.ok) {
          console.error('Jose AI provider status', response.status);
          if (response.status === 401 || response.status === 403) {
            return sendJson(res, 503, { error: 'Jose AI authentication failed. The operator must replace JOSE_AI_API_KEY with a valid OpenAI API key on Render.' });
          }
          if (response.status === 429) {
            return sendJson(res, 503, { error: 'Jose AI provider is rate-limited or out of API quota. Contact the operator.' });
          }
          return sendJson(res, 502, { error: 'Jose could not get an AI response. Please try again later.' });
        }
        const data = await response.json();
        const answer = data?.choices?.[0]?.message?.content;
        if (typeof answer !== 'string' || !answer.trim()) return sendJson(res, 502, { error: 'The AI provider returned no answer.' });
        return sendJson(res, 200, { answer: answer.trim() });
      } catch (error) {
        console.error('Jose AI request failed', error?.name);
        return sendJson(res, 504, { error: 'Jose timed out while answering. Try again.' });
      } finally { clearTimeout(timeout); }
    }

    // ---- email composer and explicit Gmail send ----
    if (req.method === 'POST' && url.pathname === '/api/email/send') {
      const user = getCurrentUser(req);
      if (!user) return sendJson(res, 401, { error: 'Sign in to send email.' });
      let body;
      try { body = await readBody(req); } catch { return sendJson(res, 400, { error: 'Invalid JSON body.' }); }
      const to = typeof body.to === 'string' ? body.to.trim() : '';
      const subject = typeof body.subject === 'string' ? body.subject.trim() : '';
      const text = typeof body.text === 'string' ? body.text.trim() : '';
      if (!body.confirmSend) return sendJson(res, 400, { error: 'Set confirmSend=true after reviewing the message.' });
      if (!to || !subject || !text || to.length > 320 || subject.length > 200 || text.length > 20000) {
        return sendJson(res, 400, { error: 'Recipient, subject, and message are required.' });
      }
      const connection = db.getConnection(user.id, 'google');
      if (!connection?.accessToken) return sendJson(res, 409, { error: 'Connect Google/Gmail in Plugins before sending email.' });
      const raw = [`To: ${to}`, `Subject: ${subject}`, 'Content-Type: text/plain; charset=utf-8', '', text].join('\\r\\n');
      const encoded = Buffer.from(raw).toString('base64url');
      const response = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/messages/send', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + decryptSecret(connection.accessToken), 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw: encoded }),
      });
      if (!response.ok) return sendJson(res, 502, { error: 'Gmail could not send this message. Reconnect Google and try again.' });
      const sent = await response.json();
      return sendJson(res, 200, { ok: true, provider: 'gmail', messageId: sent.id || null });
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
      });
      const token = randomToken();
      db.createSession({ token, userId: user.id, expiresAt: Date.now() + SESSION_TTL_MS });
      res.setHeader('Set-Cookie', `${SESSION_COOKIE}=${token}; HttpOnly; Path=/; Max-Age=${SESSION_TTL_MS / 1000}`);
      return sendJson(res, 201, { email: user.email });
    }

    if (req.method === 'POST' && url.pathname === '/api/login') {
      const { email, password } = await readBody(req);
      const user = db.getUserByEmail(String(email || '').trim().toLowerCase());
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
