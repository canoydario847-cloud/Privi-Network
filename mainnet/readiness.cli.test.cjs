'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { mkdtempSync, writeFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join } = require('node:path');

test('mainnet CLI never exits zero on unverified evidence, even if structurally complete', () => {
  const dir = mkdtempSync(join(tmpdir(), 'privi-mainnet-no-go-'));
  try {
    const manifest = {
      chain_id: 'privi-production-1',
      genesis_sha256: 'a'.repeat(64),
      binary_sha256: 'b'.repeat(64),
      validator_signoffs: Array.from({length: 4}, (_, i) => ({
        validator_id: 'v' + i,
        signature_reference: 'attestation-' + i
      })),
      audit_approval: 'unverified claim',
      rehearsal_report: 'unverified claim',
      rollback_plan: 'unverified claim'
    };
    const file = join(dir, 'manifest.json');
    writeFileSync(file, JSON.stringify(manifest));
    const child = spawnSync(process.execPath, [join(__dirname, 'readiness.cjs'), file], {encoding: 'utf8'});
    assert.equal(child.status, 1);
    assert.match(child.stderr, /NO-GO/);
    assert.match(child.stderr, /unverified/);
  } finally {
    rmSync(dir, {recursive: true, force: true});
  }
});
