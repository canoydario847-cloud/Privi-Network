// A small JSON-file-backed store. This is intentionally simple (no native
// deps, so it runs anywhere Node runs without npm install) — fine for a
// first version; swap for a real database (Render Postgres, etc.) once
// usage grows past what a single JSON file comfortably handles.
import { readFileSync, writeFileSync, existsSync, renameSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DB_FILE = process.env.DB_FILE || path.join(__dirname, '../data/db.json');

function load() {
  if (!existsSync(DB_FILE)) {
    return { users: {}, sessions: {}, connections: {} };
  }
  try {
    return JSON.parse(readFileSync(DB_FILE, 'utf8'));
  } catch {
    return { users: {}, sessions: {}, connections: {} };
  }
}

let state = load();

function persist() {
  // Write to a temp file then rename, so a crash mid-write can't corrupt
  // the store.
  const tmp = DB_FILE + '.tmp';
  writeFileSync(tmp, JSON.stringify(state, null, 2));
  renameSync(tmp, DB_FILE);
}

export const db = {
  // --- users ---
  getUserByEmail(email) {
    return Object.values(state.users).find((u) => u.email === email) || null;
  },
  getUser(id) {
    return state.users[id] || null;
  },
  createUser(user) {
    state.users[user.id] = user;
    persist();
    return user;
  },

  // --- sessions ---
  createSession(session) {
    state.sessions[session.token] = session;
    persist();
    return session;
  },
  getSession(token) {
    return state.sessions[token] || null;
  },
  deleteSession(token) {
    delete state.sessions[token];
    persist();
  },

  // --- plugin connections (one per user per plugin) ---
  setConnection(userId, pluginId, record) {
    state.connections[userId] = state.connections[userId] || {};
    state.connections[userId][pluginId] = record;
    persist();
  },
  getConnection(userId, pluginId) {
    return state.connections[userId]?.[pluginId] || null;
  },
  getConnectionsForUser(userId) {
    return state.connections[userId] || {};
  },
  removeConnection(userId, pluginId) {
    if (state.connections[userId]) {
      delete state.connections[userId][pluginId];
      persist();
    }
  },

  // Prelaunch NONFINANCIAL credits only; no on-chain PRVI or transferable value.
  getParticipationBalance(subjectId, nowMs = Date.now()) {
    const row = state.participation?.accounts?.[subjectId];
    const today = new Date(nowMs).toISOString().slice(0, 10);
    return {
      subjectId,
      totalPoints: row?.totalPoints || 0,
      todayPoints: row?.day === today ? row.dayPoints : 0,
      lastVerifiedAt: row?.lastVerifiedAt || null,
      unit: 'NONTRANSFERABLE_PARTICIPATION_POINTS',
      financialPrviAmount: 0,
    };
  },

  creditParticipation(quote, nowMs = Date.now()) {
    // ONLY call after the server verifies an issuer HMAC and original evidence.
    state.participation ||= { receipts: {}, accounts: {} };
    const ledger = state.participation;
    const receiptKey = 'work:' + quote.proofId; // Prefix protects object dictionaries from prototype keys.
    if (Object.prototype.hasOwnProperty.call(ledger.receipts, receiptKey)) {
      return { duplicate: true, ...this.getParticipationBalance(quote.subjectId, nowMs) };
    }
    // Bound storage; never delete recent deduplication evidence.
    if (Object.keys(ledger.receipts).length > 25000) {
      for (const [id, claim] of Object.entries(ledger.receipts)) {
        if (nowMs - claim.at > 31 * 86400 * 1000) delete ledger.receipts[id];
      }
      if (Object.keys(ledger.receipts).length > 25000) {
        throw new Error('Participation ledger storage cap reached');
      }
    }
    if (!ledger.accounts[quote.subjectId] &&
        Object.keys(ledger.accounts).length > 10000) {
      throw new Error('Participation account storage cap reached');
    }
    const today = new Date(nowMs).toISOString().slice(0, 10);
    const previous = ledger.accounts[quote.subjectId] || {
      totalPoints: 0, day: today, dayPoints: 0, lastVerifiedAt: null,
    };
    const usedToday = previous.day === today ? previous.dayPoints : 0;
    const granted = Math.max(0, Math.min(quote.requestedPoints, quote.dailyCap - usedToday));
    if (!Number.isSafeInteger(previous.totalPoints + granted)) {
      throw new Error('Participation point counter exceeded safe integer limit');
    }
    ledger.receipts[receiptKey] = { at: nowMs, subjectId: quote.subjectId };
    ledger.accounts[quote.subjectId] = {
      totalPoints: previous.totalPoints + granted,
      day: today, dayPoints: usedToday + granted,
      lastVerifiedAt: new Date(nowMs).toISOString(),
    };
    persist();
    return {
      duplicate: false, grantedPoints: granted,
      ...this.getParticipationBalance(quote.subjectId, nowMs),
    };
  },
};
