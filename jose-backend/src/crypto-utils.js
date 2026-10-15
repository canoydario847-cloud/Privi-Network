// Password hashing (scrypt) and at-rest encryption for stored OAuth tokens
// (AES-256-GCM), using only Node's built-in crypto — no dependencies.
import { scryptSync, randomBytes, timingSafeEqual, createCipheriv, createDecipheriv } from 'crypto';

export function hashPassword(password) {
  const salt = randomBytes(16);
  const hash = scryptSync(password, salt, 64);
  return `${salt.toString('hex')}:${hash.toString('hex')}`;
}

export function verifyPassword(password, stored) {
  const [saltHex, hashHex] = stored.split(':');
  const salt = Buffer.from(saltHex, 'hex');
  const hash = Buffer.from(hashHex, 'hex');
  const candidate = scryptSync(password, salt, 64);
  return candidate.length === hash.length && timingSafeEqual(candidate, hash);
}

function getAppKey() {
  const secret = process.env.APP_SECRET;
  if (!secret) {
    throw new Error(
      'APP_SECRET is not set. Set a long random value for it before storing any credentials.'
    );
  }
  // Derive a 32-byte key from whatever-length secret the operator set.
  return scryptSync(secret, 'jose-app-secret-salt', 32);
}

export function encryptSecret(plaintext) {
  const key = getAppKey();
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', key, iv);
  const ciphertext = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return [iv.toString('hex'), tag.toString('hex'), ciphertext.toString('hex')].join(':');
}

export function decryptSecret(stored) {
  const key = getAppKey();
  const [ivHex, tagHex, dataHex] = stored.split(':');
  const decipher = createDecipheriv('aes-256-gcm', key, Buffer.from(ivHex, 'hex'));
  decipher.setAuthTag(Buffer.from(tagHex, 'hex'));
  const plaintext = Buffer.concat([
    decipher.update(Buffer.from(dataHex, 'hex')),
    decipher.final(),
  ]);
  return plaintext.toString('utf8');
}

export function randomToken(bytes = 32) {
  return randomBytes(bytes).toString('hex');
}
