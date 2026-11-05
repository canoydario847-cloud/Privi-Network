'use strict';
// Research-only arithmetic: availability of a fixed committee is not POP liveness.
const test = require('node:test');
const assert = require('node:assert/strict');

const quorum = n => Math.floor(2 * n / 3) + 1;
const faultBound = n => Math.floor((n - 1) / 3);

test('candidate static quorum can form with at most f offline validators', () => {
  for (let n = 4; n <= 31; n++) {
    const f = faultBound(n);
    const q = quorum(n);
    assert.ok(n - f >= q, `N=${n}: f=${f} offline must leave q=${q} signers`);
    for (let offline = 0; offline <= f; offline++) {
      assert.ok(n - offline >= q, `N=${n}, offline=${offline}`);
    }
  }
});

test('exact offline blocking boundary matches candidate quorum threshold', () => {
  for (let n = 4; n <= 31; n++) {
    const f = faultBound(n);
    const q = quorum(n);
    // The chosen threshold may permit f+1 offline at some sizes; do not
    // incorrectly assert a tight bound. Test the exact blocking count.
    const minimumBlockingOffline = n - q + 1;
    assert.ok(minimumBlockingOffline >= f + 1, `N=${n}: fault tolerance floor`);
    assert.equal(n - (minimumBlockingOffline - 1), q, `N=${n}: boundary forms quorum`);
    assert.equal(n - minimumBlockingOffline, q - 1, `N=${n}: boundary blocks quorum`);
  }
});
