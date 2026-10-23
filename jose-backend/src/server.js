import http from 'http';
import { readFileSync, existsSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import crypto from 'crypto';
import { db } from './store.js';
import { hashPassword, verifyPassword, encryptSecret, decryptSecret, randomToken } from './crypto-utils.js';
import { plugins, getPlugin } from './plugins/index.js';
import { createNetworkMonitor } from './network-monitor.js';
import { createParticipationEngine, getAgentActor, POLICY } from './participation.js';

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

// Jose checks ONLY fixed, server-owned Privi endpoints every five seconds.
// These are web-service checks, not native blockchain quorum verification.
const monitor = createNetworkMonitor();
const participation = createParticipationEngine({ store: db });

function participationActor(req) {
  // Explicit invalid Bearer credentials must never fall back to a browser cookie.
  if (req.headers.authorization) return getAgentActor(req.headers.authorization);
  const user = getCurrentUser(req);
  return user ? 'user:' + user.id : null;
}

function canMutateParticipation(req) {
  if (!req.headers.origin) return Boolean(req.headers.authorization);
  try {
    const origin = new URL(req.headers.origin);
    return (origin.protocol === 'https:' ||
      (origin.protocol === 'http:' && origin.hostname === 'localhost')) &&
      origin.host === req.headers.host;
  } catch { return false; }
}

function sendJson(res, status, obj) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
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
      return sendJson(res, 200, { email: user.email, plugins: publicPluginList(user) });
    }

    // ---- Jose live service report card and beta participation credits ----
    if (req.method === 'GET' && url.pathname === '/health') {
      return sendJson(res, 200, { ok: true, service: 'jose-backend',
        monitorRunning: true, realPrviIssued: false });
    }
    if (req.method === 'GET' && url.pathname === '/api/network/report-card') {
      return sendJson(res, 200, monitor.report());
    }
    if (req.method === 'GET' && url.pathname === '/api/rewards/policy') {
      return sendJson(res, 200, {
        ...POLICY,
        eligibility: 'Authenticated sessions or preconfigured agent Bearer tokens only',
      });
    }
    if (url.pathname === '/api/rewards/me' && req.method === 'GET') {
      const actor = participationActor(req);
      if (!actor) return sendJson(res, 401, { error: 'Authentication required.' });
      return sendJson(res, 200, participation.get(actor, monitor.report()));
    }
    if (url.pathname === '/api/rewards/heartbeat' && req.method === 'POST') {
      const actor = participationActor(req);
      if (!actor) return sendJson(res, 401, { error: 'Authentication required.' });
      if (!canMutateParticipation(req)) return sendJson(res, 403, { error: 'Origin not permitted.' });
      return sendJson(res, 200, participation.heartbeat(actor, monitor.report()));
    }
    if (url.pathname === '/api/network/inspect' && req.method === 'POST') {
      const actor = participationActor(req);
      if (!actor) return sendJson(res, 401, { error: 'Authentication required.' });
      if (!canMutateParticipation(req)) return sendJson(res, 403, { error: 'Origin not permitted.' });
      const report = monitor.report();
      const result = participation.inspect(actor, report);
      return sendJson(res, 200, { ...result, report });
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
  monitor.start();
  console.log(`Jose backend listening on ${BASE_URL} — network checks every 5 seconds while process is running`);
  for (const p of plugins) {
    console.log(`  ${p.name}: ${p.isConfigured() ? 'configured' : `NOT configured (missing ${p.missingEnvVars().join(', ')})`}`);
  }
});
