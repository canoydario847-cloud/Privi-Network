'use strict';
// Offline verification helper only. Trusted keys and version floors MUST be supplied
// from independently authorized configuration, never from the manifest itself.
const {createPublicKey, verify} = require('node:crypto');
const MAX_SAFE_VERSION = BigInt(Number.MAX_SAFE_INTEGER);
function canonicalPolicy(p) {
  if (!p || typeof p !== 'object' || Array.isArray(p) ||
      Object.keys(p).sort().join(',') !== 'chainId,denom,maxSupply,version' ||
      typeof p.chainId !== 'string' || !/^[a-zA-Z0-9._-]{1,128}$/.test(p.chainId) ||
      typeof p.denom !== 'string' || !/^[a-zA-Z][a-zA-Z0-9/._-]{0,127}$/.test(p.denom) ||
      typeof p.maxSupply !== 'string' || !/^(0|[1-9][0-9]*)$/.test(p.maxSupply) ||
      BigInt(p.maxSupply) > (1n << 256n) - 1n ||
      !Number.isSafeInteger(p.version) || p.version < 1) throw Error('invalid policy');
  return Buffer.from(JSON.stringify({chainId:p.chainId,denom:p.denom,maxSupply:p.maxSupply,version:p.version}), 'utf8');
}
function verifySignedPolicy(envelope, trustedKeys, expectedChainId, minVersion) {
  try {
    if (!envelope || Object.keys(envelope).sort().join(',') !== 'keyId,policy,signature' ||
        typeof envelope.keyId !== 'string' || !Object.hasOwn(trustedKeys || {}, envelope.keyId) ||
        typeof expectedChainId !== 'string' || !Number.isSafeInteger(minVersion) ||
        minVersion < 1 || minVersion > Number(MAX_SAFE_VERSION)) return false;
    const bytes = canonicalPolicy(envelope.policy);
    if (envelope.policy.chainId !== expectedChainId || envelope.policy.version < minVersion ||
        typeof envelope.signature !== 'string' ||
        !/^[A-Za-z0-9+/]{86}==$/.test(envelope.signature)) return false;
    const signature = Buffer.from(envelope.signature, 'base64');
    if (signature.length !== 64 || signature.toString('base64') !== envelope.signature) return false;
    const key = createPublicKey(trustedKeys[envelope.keyId]);
    if (key.asymmetricKeyType !== 'ed25519') return false;
    return verify(null, bytes, key, signature);
  } catch { return false; }
}
module.exports = {canonicalPolicy, verifySignedPolicy};
