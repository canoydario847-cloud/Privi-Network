# PoP research multi-round machine

**Status: RESEARCH ONLY.** Not production PoP consensus, not mainnet, not PRVI issuance.

## Module

- `round_machine.cjs` — height-scoped driver: `propose → prevote → precommit → commit`
- `test_round_machine.cjs` — unit tests (8 cases)

Builds on `engine.cjs` certificates. Precommit quorum uses the same commit-tag signatures as `verifyCertificate`.

## What it adds

- Caller-driven phase timeouts with linear round backoff
- View-change (`onTimeout`) to the next round while retaining locks only after precommit
- In-memory `ResearchVoteLock` on precommit (pair with `persistent_vote_guard.cjs` for durable experiments)
- Every decision sets `productionConsensus: false`

## What it does not do

- Network transport / peer gossip
- Crash-safe locks by itself
- Byzantine partition safety proofs
- ABCI / CometBFT replacement
- Financial activation

## Test

```bash
cd production-network/mainnet/pop_candidate
node --test test_round_machine.cjs
```

Passing tests is **not** evidence of live PoP finality.
