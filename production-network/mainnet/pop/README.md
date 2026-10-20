# Point of Position (PoP) — offline logical-position verifier

**Status: development prototype only. Native PoP BFT consensus is NOT implemented, audited or deployed.**

This prototype translates the record-sealing portion of Dario Canoy's *Point of Position: A New Framework for True Asset Valuation* (September 2026, supplied as `POP(1).pdf`) into testable Go code. PoP here means a **logical company/zone/sequence position**; it is **not** Proof of Stake (PoS), Point of Sale or a GPS coordinate.

The paper defines `pop_stamp`, `pop_zone` and `pop_verified`. This package verifies `PoP:COMPANY:ZONE:SEQUENCE` stamps, a limited whitelist of the paper's zone names, deterministic length-prefixed domain-separated commitments, Ed25519 authorship against an **externally pinned** public key, SHA-256 linkage, and gap/replay rejection within one company's zone from sequence 1. No self-reported `pop_verified` flag is trusted. The verifier returns `PoPVerified` only after validating the supplied records.

## Test

```bash
cd production-network/mainnet/pop
go test -count=1 ./...
```

The existing offline CI runs this command. Tests generate throwaway in-memory Ed25519 identities; no real wallet, validator key, token, genesis or network is touched.

## What is *not* proven

- This code is **not** a consensus state machine, CometBFT replacement, PoP validator election rule, safety/liveness argument or independent finality proof.
- It does **not** establish that a claimed company legitimately owns a signer. A future consensus-backed company-to-key authorization registry, revocation policy and rotation rules must be designed and audited; here the caller must pin the exact expected signer.
- A valid signed commitment does **not** independently prove physical asset existence, sensor truthfulness, independent event sourcing or economic collateral value.
- No zone USD prices, automatic PRVI credit, reward yield, token issuance, financial settlement or proposed high-gas revenue assumptions are encoded. The paper's fixed BTC/ETH reference values are **informational examples**, not current exchange rates, reserves or enforceable collateral.
- Prototype verification starts at sequence 1 and uses an O(history length) scan, bounded to 10,000 records. Production would need a consensus-backed checkpoint, deterministic state transitions, immutable storage and benchmarked performance.
- The sole proposed operator remains Privi World Corp; the sole candidate owner/treasury wallet remains `0x1990589FD200E043b8C6FD9ec5956c61b3071048`. Neither wallet control nor permission is established by this verifier.

**Financial mainnet remains NO-GO** until the native PoP BFT protocol is specified, implemented and independently audited alongside Cosmos SDK PRVI supply/fee routes, signed genesis/release and securely operated validator hosts.
