'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only model: signer identities are NOT cryptographic signatures.
// A real verifier must authenticate signatures over an unambiguous encoding
// including chain ID, epoch, height, round, and block ID.
function acceptsCertificate(expected, certificate) {
  if (!expected || !certificate || typeof expected !== 'object' || typeof certificate !== 'object') return false;
  const fields = ['chainId', 'epoch', 'height', 'round', 'blockId'];
  if (!fields.every(key => Object.hasOwn(expected, key) && Object.hasOwn(certificate, key))) return false;
  if (!fields.every(key => typeof expected[key] === 'string' && expected[key].length > 0 &&
    typeof certificate[key] === 'string' && certificate[key] === expected[key])) return false;
  if (!Array.isArray(expected.committee) || !Array.isArray(certificate.signers)) return false;
  const members = expected.committee;
  if (members.length < 4 || members.length > 31 ||
      !members.every(id => typeof id === 'string' && id.length > 0) ||
      new Set(members).size !== members.length) return false;
  const signers = certificate.signers;
  if (!signers.every(id => typeof id === 'string' && id.length > 0 && members.includes(id))) return false;
  return new Set(signers).size >= Math.floor(2 * members.length / 3) + 1;
}

test('candidate POP certificate context must reject cross-chain, cross-epoch, and conflicting-block replay', () => {
  const expected = {chainId: 'privi-native', epoch: '4', height: '100', round: '2', blockId: 'block-A', committee: ['a','b','c','d']};
  const certificate = {chainId: 'privi-native', epoch: '4', height: '100', round: '2', blockId: 'block-A', signers: ['a','b','c']};
  assert.equal(acceptsCertificate(expected, certificate), true);
  for (const field of ['chainId', 'epoch', 'height', 'round', 'blockId']) {
    assert.equal(acceptsCertificate(expected, {...certificate, [field]: 'other'}), false, field);
    const missing = {...certificate}; delete missing[field];
    assert.equal(acceptsCertificate(expected, missing), false, `missing ${field}`);
  }
  assert.equal(acceptsCertificate(expected, {...certificate, signers: ['a','a','a']}), false);
  assert.equal(acceptsCertificate(expected, {...certificate, signers: ['a','b','outsider']}), false);
  assert.equal(acceptsCertificate(expected, {...certificate, signers: ['a','b']}), false);
});
