# PoP research: linked certificate batch verifier

This is a **research-only, read-only verification experiment**, not a production blockchain, client, consensus state machine, or proof of finality. It extends the signed committee certificate prototype with a check that a sequence has no missing or duplicated heights, cryptographically valid research proposals and quorum votes, and an exact previous-block hash link to an externally supplied anchor.

Run from the repository root:

```bash
node --test production-network/mainnet/pop_candidate/test_linked_certificate_verifier.cjs
```

The new test is also covered by `.github/workflows/privi-pop-research-safety.yml`, which runs `test_*.cjs` on changes in this directory.

## Required inputs and limitations

- An already verified **research committee** from `parseRegistry`; no mainnet committee or stake-based consensus is supported.
- A caller-provided `anchorHeight` and `anchorHash`. For height zero, the hash must equal the committee's pinned genesis identity. For later heights, **the anchor is not authenticated by this verifier** and a malicious caller can pick an arbitrary anchor.
- A nonempty array of at most 128 signed `{proposal, votes}` bundles in strictly increasing, contiguous heights. All certificates use the **same** research committee and epoch; joint-consensus changes are deliberately unsupported.
- A signed proposal and sufficient distinct Ed25519 commit signatures must verify for every bundle.

The successful result always says `productionConsensus: false`, `productionFinality: false`, and `anchorTrustVerified: false`. A cryptographically consistent sequence does **not** prove that blocks were executed, data was available, the validator failure domains were real, Byzantine nodes were below the threshold, or a real network agreed on the sequence. It does not detect malicious **competing** signed sequences from a compromised signing quorum, and it does not replace persistent signer state or a formalized lock/view-change protocol. No PRVI financial transfers, minting, validators, or RPCs are activated by this code.
