# Point of Position (PoP) — offline logical-position verifier

**Status: consensus-KV state-transition prototype only. CometBFT-backed native PoP enforcement is NOT wired into the customized app, audited or deployed.**

This prototype translates the record-sealing portion of Dario Canoy's *Point of Position: A New Framework for True Asset Valuation* (September 2026, supplied as `POP(1).pdf`) into testable Go code. PoP here means a **logical company/zone/sequence position**; it is **not** Proof of Stake (PoS), Point of Sale or a GPS coordinate.

The paper defines `pop_stamp`, `pop_zone` and `pop_verified`. This package verifies `PoP:COMPANY:ZONE:SEQUENCE` stamps, a limited whitelist of the paper's zone names, deterministic length-prefixed domain-separated commitments, Ed25519 authorship against an **externally pinned** public key, SHA-256 linkage, and gap/replay rejection within one company's zone from sequence 1. No self-reported `pop_verified` flag is trusted. The verifier returns `PoPVerified` only after validating the supplied records.

## Test

```bash
cd production-network/mainnet/pop
go test -count=1 ./...
```

The existing offline CI runs this command with \`-mod=mod\`. Tests generate throwaway in-memory Ed25519 identities; no real wallet, validator key, token, genesis or network is touched. The \`Keeper\` implements a deterministic candidate transition over Cosmos SDK \`corestore.KVStoreService\`, with an immutable sorted company/zone author registry, consensus-store position checkpoints, monotonic sequence checks, and one KV write per accepted position. Its current unit tests use a fake KV store and reopen a second keeper over the same mock state; **this is not yet a real SDK Commit/FinalizeBlock or disk-restart test**.\n\n**Owner-approved engineering choice (2026-10-20):** CometBFT will provide Byzantine voting and commit finality, while PoP will supply Privi-specific mandatory consensus-validated company/zone/sequence transitions. This separates the PoP data protocol from the voting engine without treating PoP as Proof of Stake or PoSA.

## What is *not* proven

- The \`Keeper.Apply\` prototype is a consensus-store **candidate state transition**, but it is **not mounted in the actual customized Cosmos EVM app**, called from ABCI/FinalizeBlock, required by transaction admission, or tested on persistent LevelDB/IAVL. It is not a CometBFT replacement, PoP validator election rule, safety/liveness argument or independent finality proof.
- The prototype genesis registry pins one Ed25519 public signer per company/zone and rejects duplicate or post-genesis reinitialization. It does **not** establish who legally owns a company, prove an IoT sensor, or implement authenticated key rotation/revocation; approved registry updates must be separately designed and reviewed before production.
- A valid signed commitment does **not** independently prove physical asset existence, sensor truthfulness, independent event sourcing or economic collateral value.
- No zone USD prices, automatic PRVI credit, reward yield, token issuance, financial settlement or proposed high-gas revenue assumptions are encoded. The paper's fixed BTC/ETH reference values are **informational examples**, not current exchange rates, reserves or enforceable collateral.
- The offline \`VerifyChain\` validator scans up to 10,000 events from sequence 1. \`Keeper.Apply\` validates one record against a persisted checkpoint and writes a new tip, but presently reads an up-to-256-authority registry on every call and has no batching/rollback proof, actual SDK durable-state proof, transaction integration or performance benchmark.
- The sole proposed operator remains Privi World Corp; the sole candidate owner/treasury wallet remains `0x1990589FD200E043b8C6FD9ec5956c61b3071048`. Neither wallet control nor permission is established by this verifier.

**Financial mainnet remains NO-GO** until the native PoP BFT protocol is specified, implemented and independently audited alongside Cosmos SDK PRVI supply/fee routes, signed genesis/release and securely operated validator hosts.
