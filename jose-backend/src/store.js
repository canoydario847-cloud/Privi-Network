// A small JSON-file-backed store. This is intentionally simple (no native
// deps, so it runs anywhere Node runs without npm install) — fine for a
// first version; swap for a real database (Render Postgres, etc.) once
// usage grows past what a single JSON file comfortably handles.
import { readFileSync, writeFileSync, existsSync, renameSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DB_FILE = process.env.DB_FILE || path.join(__dirname, '../data/db.json');

const EMPTY = () => ({ users: {}, sessions: {}, connections: {}, payments: {}, listings: {} });

function load() {
  let loaded = EMPTY();
  if (existsSync(DB_FILE)) {
    try {
      loaded = JSON.parse(readFileSync(DB_FILE, 'utf8'));
    } catch {
      loaded = EMPTY();
    }
  }
  // v3 added payments + listings; older db.json files simply lack them.
  return { ...EMPTY(), ...loaded };
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

  // --- v3: user fields (wallet, credits) ---
  updateUser(id, fields) {
    if (!state.users[id]) return null;
    Object.assign(state.users[id], fields);
    persist();
    return state.users[id];
  },
  getUserByWallet(address) {
    const a = String(address || '').toLowerCase();
    return Object.values(state.users).find((u) => u.wallet && u.wallet.toLowerCase() === a) || null;
  },
  // Atomic-enough for a single-process server: check and change in one call.
  spendCredits(id, amount) {
    const u = state.users[id];
    if (!u || (u.credits || 0) < amount) return false;
    u.credits -= amount;
    persist();
    return true;
  },
  addCredits(id, amount) {
    const u = state.users[id];
    if (!u) return null;
    u.credits = (u.credits || 0) + amount;
    persist();
    return u.credits;
  },

  // --- v3: JOSE payments (each tx hash can be claimed once) ---
  getPayment(txHash) {
    return state.payments[txHash.toLowerCase()] || null;
  },
  recordPayment(payment) {
    state.payments[payment.txHash.toLowerCase()] = payment;
    persist();
  },
  getPaymentsForUser(userId) {
    return Object.values(state.payments).filter((p) => p.userId === userId).sort((a, b) => b.claimedAt - a.claimedAt);
  },

  // --- v3: NFT marketplace listings ---
  createListing(listing) {
    state.listings[listing.id] = listing;
    persist();
    return listing;
  },
  getListing(id) {
    return state.listings[id] || null;
  },
  findActiveListing(contract, tokenId) {
    const c = contract.toLowerCase();
    return Object.values(state.listings).find((l) => l.status === 'active' && l.contract.toLowerCase() === c && l.tokenId === tokenId) || null;
  },
  listListings({ status = 'active', seller } = {}) {
    return Object.values(state.listings)
      .filter((l) => (!status || l.status === status) && (!seller || l.seller.toLowerCase() === seller.toLowerCase()))
      .sort((a, b) => b.createdAt - a.createdAt);
  },
  updateListing(id, fields) {
    if (!state.listings[id]) return null;
    Object.assign(state.listings[id], fields);
    persist();
    return state.listings[id];
  },
};
