import test from 'node:test';
import assert from 'node:assert/strict';
import {
  keccak256, addressFromPrivateKey, hashPersonalMessage, signHash, recoverPersonalSign, TRANSFER_TOPIC,
} from '../src/eth.js';

test('keccak256 known vectors', () => {
  assert.equal(keccak256('').toString('hex'), 'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470');
  assert.equal(keccak256('abc').toString('hex'), '4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45');
  // longer than one 136-byte block
  assert.equal(keccak256('a'.repeat(200)).length, 32);
  assert.equal(TRANSFER_TOPIC, '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef');
});

test('address from private key 1', () => {
  assert.equal(addressFromPrivateKey('0x1'), '0x7e5f4552091a69125d5dfcb7b8c2659029395bdf');
});

test('personal_sign round trip', () => {
  const priv = '0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318';
  const addr = addressFromPrivateKey(priv);
  assert.equal(addr, '0x2c7536e3605d9c16a7a3d7b1898e529396a65c23');
  const msg = 'Link this wallet to my Jose account\nNonce: abc123';
  const sig = signHash(hashPersonalMessage(msg), priv);
  assert.equal(recoverPersonalSign(msg, sig), addr);
  assert.notEqual(recoverPersonalSign(msg + 'x', sig), addr);
});

test('recovers a known web3 signature', () => {
  // web3.js docs: web3.eth.accounts.sign('Some data', '0x4c08...2318')
  const sig = '0xb91467e570a6466aa9e9876cbcd013baba02900b8979d43fe208a4a4f339f5fd6007e74cd82e037b800186422fc2da167c747ef045e5d18a5f5d4300f8e1a0291c';
  assert.equal(recoverPersonalSign('Some data', sig), '0x2c7536e3605d9c16a7a3d7b1898e529396a65c23');
});
