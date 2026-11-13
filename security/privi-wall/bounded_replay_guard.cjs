'use strict';
/**
 * Privi Wall bounded replay admission prototype.
 * Single-process only. A distributed deployment MUST use an atomic shared store.
 * No third-party dependencies. Not an RFC 9421 implementation.
 */
const crypto = require('node:crypto');
class BoundedReplayGuard {
  constructor({capacity = 10000, maxLifetimeMs = 60000, clock = Date.now} = {}) {
    if (!Number.isSafeInteger(capacity) || capacity < 1 || !Number.isSafeInteger(maxLifetimeMs) || maxLifetimeMs < 1 || typeof clock !== 'function') throw new TypeError('invalid config');
    this.capacity=capacity;this.maxLifetimeMs=maxLifetimeMs;this.clock=clock;this.entries=new Map();
  }
  consume({tenant,nonce,expiresAt}) {
    const now=this.clock();
    if(typeof tenant!=='string'||!/^[A-Za-z0-9_-]{1,64}$/.test(tenant)||typeof nonce!=='string'||!/^[a-f0-9]{32,64}$/.test(nonce)) throw new Error('invalid identity');
    if(!Number.isSafeInteger(expiresAt)||expiresAt<=now||expiresAt>now+this.maxLifetimeMs) throw new Error('invalid expiry');
    for(const [key,expiry] of this.entries) if(expiry<=now)this.entries.delete(key);
    const key=crypto.createHash('sha256').update(JSON.stringify([tenant,nonce])).digest('hex');
    if(this.entries.has(key))throw new Error('replay');
    // Fail closed rather than evict live nonces and accidentally permit replay.
    if(this.entries.size>=this.capacity)throw new Error('replay capacity exhausted');
    this.entries.set(key,expiresAt);
    return true;
  }
}
module.exports={BoundedReplayGuard};
