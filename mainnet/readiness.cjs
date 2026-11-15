#!/usr/bin/env node
'use strict';
// Offline structural readiness check only: no financial mainnet launch authorization.
const fs = require('node:fs');
const path = require('node:path');
const REQUIRED = ['chain_id','genesis_sha256','binary_sha256','validator_signoffs','audit_approval','rehearsal_report','rollback_plan'];
const HEX64 = /^[a-f0-9]{64}$/;
const has = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

function check(m) {
  const errors = [];
  if (!m || typeof m !== 'object' || Array.isArray(m)) return ['manifest must be an object'];
  for (const k of REQUIRED) if (!has(m, k)) errors.push('missing ' + k);
  if (typeof m.chain_id !== 'string' || !/^privi-[a-z0-9-]{3,50}$/.test(m.chain_id)) errors.push('invalid chain_id');
  for (const k of ['genesis_sha256','binary_sha256']) {
    if (typeof m[k] !== 'string' || !HEX64.test(m[k])) errors.push('invalid ' + k);
  }
  const signoffs = m.validator_signoffs;
  const validSignoffs = Array.isArray(signoffs) && signoffs.length >= 4 &&
      signoffs.every(s => s && typeof s === 'object' && !Array.isArray(s) &&
        typeof s.validator_id === 'string' && s.validator_id.trim() &&
        s.validator_id === s.validator_id.trim() &&
        typeof s.signature_reference === 'string' && s.signature_reference.trim() &&
        s.signature_reference === s.signature_reference.trim());
  if (!validSignoffs ||
      new Set(signoffs.map(s => s.validator_id)).size !== signoffs.length ||
      new Set(signoffs.map(s => s.signature_reference)).size !== signoffs.length) {
    errors.push('need four distinct nonblank validator signoff references');
  }
  for (const k of ['audit_approval','rehearsal_report','rollback_plan']) {
    if (typeof m[k] !== 'string' || !m[k].trim()) errors.push('missing evidence ' + k);
  }
  return errors;
}
if (require.main === module) {
  const file = process.argv[2];
  if (!file) { console.error('Usage: node readiness.cjs manifest.json'); process.exitCode = 2; }
  else {
    try {
      const m = JSON.parse(fs.readFileSync(path.resolve(file), 'utf8'));
      const errors = check(m);
      if (errors.length) { console.error('NO-GO: ' + errors.join('; ')); process.exitCode = 1; }
      else { console.error('NO-GO: manifest structure complete but evidence and launch authorization remain unverified.'); process.exitCode = 1; }
    } catch (e) { console.error('NO-GO: ' + e.message); process.exitCode = 1; }
  }
}
module.exports = {check};
