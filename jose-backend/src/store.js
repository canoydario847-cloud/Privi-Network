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
    return { users: {}, sessions: {}, connections: {}, rewardStates: {} };
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
  // Beta reward credits: persisted by authenticated account or agent identity.
  // Single-process JSON storage. Move to transactional SQL before multi-instance use.
  getRewardState(actor) { return state.rewardStates?.[actor] || null; },
  putRewardState(actor, record) {
    state.rewardStates = state.rewardStates || {};
    state.rewardStates[actor] = record;
    persist();
  },

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
};
