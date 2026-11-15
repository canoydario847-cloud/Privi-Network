// No network, third-party SDK, EIP-7702 delegation or money movement in this test suite.
import test from "node:test";
import assert from "node:assert/strict";
import { anchorData, validateOptions, main, BASE_CHAIN_ID, BASE_USDC } from "./anchor.mjs";

const root = "ab".repeat(32);

test("Privi Anchor calldata includes the canonical digest on Base", () => {
  assert.equal(anchorData(root), "0x5052564101" + root);
  assert.equal(anchorData("0x" + root), "0x5052564101" + root);
  assert.equal(validateOptions({ root }).chainId, BASE_CHAIN_ID);
  assert.equal(validateOptions({ root }).usdcContract, BASE_USDC);
});
test("Fail closed on invalid hashes and unknown paymaster modes", () => {
  for (const invalid of ["a", "gg".repeat(32), "", "0x" + root + "00"]) {
    assert.throws(() => anchorData(invalid), /Expected/);
  }
  assert.throws(() => validateOptions({ root, mode: "eth" }), /Mode/);
});
test("No keys, USDC funds or optional dependencies needed to dry run", async () => {
  const result = await main(["--root", root], {});
  assert.equal(result, 0);
});
test("No money movement when EIP-7702 delegation has not been authorized", async () => {
  const result = await main(["--root", root, "--execute"], {});
  assert.equal(result, 1);
});
