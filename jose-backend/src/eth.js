// Minimal, dependency-free Ethereum helpers for Jose:
//   - keccak256 (the hash Ethereum uses; not the same as NIST SHA3-256)
//   - recovering the signer address of a MetaMask `personal_sign` signature
//   - a tiny JSON-RPC client + the few ABI calls Jose needs (ERC-20 / ERC-721)
//
// Kept dependency-free on purpose, like the rest of jose-backend, so the
// server still runs with plain `node src/server.js` and no npm install.
// Tested against known vectors in test/eth.test.js.

import { randomBytes } from 'crypto';

// ---------------------------------------------------------------- keccak256
const MASK64 = (1n << 64n) - 1n;
const RC = [
  0x0000000000000001n, 0x0000000000008082n, 0x800000000000808an, 0x8000000080008000n,
  0x000000000000808bn, 0x0000000080000001n, 0x8000000080008081n, 0x8000000000008009n,
  0x000000000000008an, 0x0000000000000088n, 0x0000000080008009n, 0x000000008000000an,
  0x000000008000808bn, 0x800000000000008bn, 0x8000000000008089n, 0x8000000000008003n,
  0x8000000000008002n, 0x8000000000000080n, 0x000000000000800an, 0x800000008000000an,
  0x8000000080008081n, 0x8000000000008080n, 0x0000000080000001n, 0x8000000080008008n,
];
const ROT = [
  0, 1, 62, 28, 27, 36, 44, 6, 55, 20, 3, 10, 43, 25, 39, 41, 45, 15, 21, 8, 18, 2, 61, 56, 14,
];
const rotl = (x, n) => (n === 0 ? x : ((x << BigInt(n)) | (x >> BigInt(64 - n))) & MASK64);

function keccakF(s) {
  for (let round = 0; round < 24; round++) {
    const c = [];
    for (let x = 0; x < 5; x++) c[x] = s[x] ^ s[x + 5] ^ s[x + 10] ^ s[x + 15] ^ s[x + 20];
    for (let x = 0; x < 5; x++) {
      const d = c[(x + 4) % 5] ^ rotl(c[(x + 1) % 5], 1);
      for (let y = 0; y < 25; y += 5) s[y + x] ^= d;
    }
    const b = new Array(25);
    for (let x = 0; x < 5; x++) {
      for (let y = 0; y < 5; y++) {
        b[y + 5 * ((2 * x + 3 * y) % 5)] = rotl(s[x + 5 * y], ROT[x + 5 * y]);
      }
    }
    for (let y = 0; y < 25; y += 5) {
      for (let x = 0; x < 5; x++) {
        s[y + x] = b[y + x] ^ (~b[y + ((x + 1) % 5)] & MASK64 & b[y + ((x + 2) % 5)]);
      }
    }
    s[0] ^= RC[round];
  }
}

export function keccak256(input) {
  const data = typeof input === 'string' ? Buffer.from(input, 'utf8') : Buffer.from(input);
  const rate = 136;
  const padLen = rate - (data.length % rate);
  const msg = Buffer.concat([data, Buffer.alloc(padLen)]);
  msg[data.length] ^= 0x01;
  msg[msg.length - 1] ^= 0x80;
  const s = new Array(25).fill(0n);
  for (let off = 0; off < msg.length; off += rate) {
    for (let i = 0; i < rate / 8; i++) s[i] ^= msg.readBigUInt64LE(off + i * 8);
    keccakF(s);
  }
  const out = Buffer.alloc(32);
  for (let i = 0; i < 4; i++) out.writeBigUInt64LE(s[i], i * 8);
  return out;
}

// ---------------------------------------------------------------- secp256k1
const P = 0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffefffffc2fn;
const N = 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141n;
const G = [
  0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798n,
  0x483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8n,
];
const mod = (a, m = P) => ((a % m) + m) % m;
function modPow(b, e, m) {
  let r = 1n;
  b = mod(b, m);
  while (e > 0n) {
    if (e & 1n) r = (r * b) % m;
    b = (b * b) % m;
    e >>= 1n;
  }
  return r;
}
const inv = (a, m = P) => modPow(a, m - 2n, m);

function pointAdd(p1, p2) {
  if (!p1) return p2;
  if (!p2) return p1;
  const [x1, y1] = p1;
  const [x2, y2] = p2;
  if (x1 === x2) {
    if (mod(y1 + y2) === 0n) return null;
    const l = mod(3n * x1 * x1 * inv(2n * y1));
    const x3 = mod(l * l - 2n * x1);
    return [x3, mod(l * (x1 - x3) - y1)];
  }
  const l = mod((y2 - y1) * inv(x2 - x1));
  const x3 = mod(l * l - x1 - x2);
  return [x3, mod(l * (x1 - x3) - y1)];
}
function pointMul(k, pt) {
  let r = null;
  let add = pt;
  while (k > 0n) {
    if (k & 1n) r = pointAdd(r, add);
    add = pointAdd(add, add);
    k >>= 1n;
  }
  return r;
}
const big = (buf) => BigInt('0x' + Buffer.from(buf).toString('hex'));
const to32 = (n) => Buffer.from(n.toString(16).padStart(64, '0'), 'hex');

export function addressFromPublicPoint([x, y]) {
  return '0x' + keccak256(Buffer.concat([to32(x), to32(y)])).subarray(12).toString('hex');
}

export function addressFromPrivateKey(privHex) {
  return addressFromPublicPoint(pointMul(BigInt(privHex), G));
}

// Ethereum `personal_sign` prefix (EIP-191).
export function hashPersonalMessage(message) {
  const msg = Buffer.from(message, 'utf8');
  const prefix = Buffer.from(`\x19Ethereum Signed Message:\n${msg.length}`, 'utf8');
  return keccak256(Buffer.concat([prefix, msg]));
}

// Signs a 32-byte hash. Used only by the tests (to round-trip recovery);
// the server never holds private keys.
export function signHash(hash, privHex) {
  const d = BigInt(privHex);
  const z = big(hash);
  for (;;) {
    const k = mod(big(randomBytes(32)), N);
    if (k === 0n) continue;
    const R = pointMul(k, G);
    const r = mod(R[0], N);
    if (r === 0n) continue;
    let s = mod(inv(k, N) * (z + r * d), N);
    if (s === 0n) continue;
    let recid = Number(R[1] & 1n);
    if (s > N / 2n) {
      s = N - s;
      recid ^= 1;
    }
    return '0x' + to32(r).toString('hex') + to32(s).toString('hex') + (27 + recid).toString(16);
  }
}
export function recoverAddress(hash, sigHex) {
  const sig = Buffer.from(String(sigHex).replace(/^0x/, ''), 'hex');
  if (sig.length !== 65) throw new Error('Signature must be 65 bytes.');
  const r = big(sig.subarray(0, 32));
  const s = big(sig.subarray(32, 64));
  let v = sig[64];
  if (v >= 27) v -= 27;
  if (v !== 0 && v !== 1) throw new Error('Bad signature recovery id.');
  if (r <= 0n || r >= N || s <= 0n || s > N / 2n) throw new Error('Signature out of range.');
  const x = r;
  const alpha = mod(x * x * x + 7n);
  let y = modPow(alpha, (P + 1n) / 4n, P);
  if (mod(y * y) !== alpha) throw new Error('Invalid signature point.');
  if (Number(y & 1n) !== v) y = P - y;
  const R = [x, y];
  const z = big(hash);
  const rInv = inv(r, N);
  const u1 = mod(-z * rInv, N);
  const u2 = mod(s * rInv, N);
  const Q = pointAdd(pointMul(u1, G), pointMul(u2, R));
  if (!Q) throw new Error('Invalid signature.');
  return addressFromPublicPoint(Q);
}

export function recoverPersonalSign(message, sigHex) {
  return recoverAddress(hashPersonalMessage(message), sigHex);
}

export const isAddress = (a) => /^0x[0-9a-fA-F]{40}$/.test(String(a || ''));
export const sameAddress = (a, b) => isAddress(a) && isAddress(b) && a.toLowerCase() === b.toLowerCase();

// ---------------------------------------------------------------- JSON-RPC
let rpcId = 0;
export async function rpc(rpcUrl, method, params = []) {
  const res = await fetch(rpcUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: ++rpcId, method, params }),
    signal: AbortSignal.timeout(15000),
  });
  const body = await res.json();
  if (body.error) throw new Error(body.error.message || 'RPC error');
  return body.result;
}

const selector = (sig) => '0x' + keccak256(sig).subarray(0, 4).toString('hex');
const encUint = (n) => BigInt(n).toString(16).padStart(64, '0');
export const TRANSFER_TOPIC = '0x' + keccak256('Transfer(address,address,uint256)').toString('hex');

function ethCall(rpcUrl, to, data) {
  return rpc(rpcUrl, 'eth_call', [{ to, data }, 'latest']);
}

function decodeAbiString(hex) {
  const buf = Buffer.from(hex.replace(/^0x/, ''), 'hex');
  if (buf.length < 64) return '';
  const offset = Number(big(buf.subarray(0, 32)));
  const len = Number(big(buf.subarray(offset, offset + 32)));
  return buf.subarray(offset + 32, offset + 32 + len).toString('utf8');
}

export async function erc20Decimals(rpcUrl, token) {
  const out = await ethCall(rpcUrl, token, selector('decimals()'));
  return Number(BigInt(out));
}

export async function erc721OwnerOf(rpcUrl, contract, tokenId) {
  const out = await ethCall(rpcUrl, contract, selector('ownerOf(uint256)') + encUint(tokenId));
  return '0x' + out.slice(-40);
}

export async function erc721TokenURI(rpcUrl, contract, tokenId) {
  try {
    const out = await ethCall(rpcUrl, contract, selector('tokenURI(uint256)') + encUint(tokenId));
    return decodeAbiString(out);
  } catch {
    return '';
  }
}

// Sums ERC-20 `Transfer` amounts of `token` from `from` to `to` inside a
// mined, successful transaction. Returns { amount: bigint, confirmations }.
export async function erc20TransferredInTx(rpcUrl, txHash, { token, from, to }) {
  const receipt = await rpc(rpcUrl, 'eth_getTransactionReceipt', [txHash]);
  if (!receipt) return { found: false, amount: 0n };
  if (receipt.status !== '0x1') return { found: true, failed: true, amount: 0n };
  const pad = (a) => '0x' + a.toLowerCase().replace(/^0x/, '').padStart(64, '0');
  let amount = 0n;
  for (const log of receipt.logs || []) {
    if (
      sameAddress(log.address, token) &&
      log.topics?.[0]?.toLowerCase() === TRANSFER_TOPIC &&
      log.topics.length === 3 &&
      log.topics[1].toLowerCase() === pad(from) &&
      log.topics[2].toLowerCase() === pad(to)
    ) {
      amount += BigInt(log.data);
    }
  }
  const head = BigInt(await rpc(rpcUrl, 'eth_blockNumber'));
  const confirmations = Number(head - BigInt(receipt.blockNumber)) + 1;
  return { found: true, amount, confirmations };
}
