// Copyright (c) 2026 Privi World Corp — Jose single-process storage regression tests.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

test('creates a private storage directory and persists provisional credits', async () => {
  const tmp = mkdtempSync(path.join(tmpdir(), 'jose-participation-'));
  const previous = process.env.DB_FILE;
  try {
    const p = path.join(tmp, 'nested', 'jose-db.json');
    process.env.DB_FILE = p;
    const { db } = await import('../src/store.js?fresh=first');
    db.putRewardState('agent:monitor01', { credits: 17, history: [] });
    assert.equal(existsSync(p), true);
    assert.equal(JSON.parse(readFileSync(p, 'utf8')).rewardStates['agent:monitor01'].credits, 17);
    assert.equal(db.getRewardState('agent:monitor01').credits, 17);
  } finally {
    if (previous === undefined) delete process.env.DB_FILE;
    else process.env.DB_FILE = previous;
    rmSync(tmp, { recursive: true, force: true });
  }
});

test('corrupted reward/account database fails closed instead of wiping state', async () => {
  const tmp = mkdtempSync(path.join(tmpdir(), 'jose-corruption-'));
  const previous = process.env.DB_FILE;
  try {
    const p = path.join(tmp, 'db.json');
    writeFileSync(p, '{not valid json');
    process.env.DB_FILE = p;
    await assert.rejects(import('../src/store.js?fresh=corrupt'), /refusing data reset/);
    assert.equal(readFileSync(p, 'utf8'), '{not valid json');
  } finally {
    if (previous === undefined) delete process.env.DB_FILE;
    else process.env.DB_FILE = previous;
    rmSync(tmp, { recursive: true, force: true });
  }
});
