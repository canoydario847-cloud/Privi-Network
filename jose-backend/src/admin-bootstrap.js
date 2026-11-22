import crypto from 'crypto';
import { db } from './store.js';
import { hashPassword } from './crypto-utils.js';

export function ensureConfiguredAdmin() {
  const email = String(process.env.JOSE_ADMIN_EMAIL || '').trim().toLowerCase();
  const password = String(process.env.JOSE_ADMIN_PASSWORD || '');
  if (!email || password.length < 8) return false;
  const existing = db.getUserByEmail(email);
  if (existing) return false;
  db.createUser({ id: crypto.randomUUID(), email, passwordHash: hashPassword(password), role: 'admin', createdAt: Date.now() });
  return true;
}
