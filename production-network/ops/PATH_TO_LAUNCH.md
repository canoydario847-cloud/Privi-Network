# Path to PRVI financial mainnet launch

**Current verdict: NO-GO — NOT LIVE**

This document sequences engineering work toward a possible future GO decision.
It is **not** authorization to activate mainnet, issue PRVI, or operate production validators.

## Non-negotiables

- All eight gates in [MAINNET_LAUNCH_GATE.md](MAINNET_LAUNCH_GATE.md) remain **BLOCKED** until evidence is real and independently verifiable.
- CI green ≠ launch approval.
- Research PoP (`pop_candidate/`) ≠ production consensus.
- Offline cap model ≠ SDK-enforced lifetime supply limit.
- Four local/Docker validators ≠ four independent operators.
- A candidate binary pin with `sha256: UNPINNED` is not a release.
- Never commit mnemonics, validator private keys, or production secrets.

## Build ladder (order matters)

| Stage | Goal | Status (2026-11-26) | Exit criteria |
| ---: | --- | --- | --- |
| **0** | Fail-closed gates & honest docs | **In place** | Guards refuse mainnet; README/ops say NO-GO |
| **1** | Research PoP safety suite + CI | **In place** | `privi-pop-research-safety.yml` green on Node 20/24 |
| **2** | Candidate binary pin | **Verifier in place; SHA UNPINNED** | Reproducible build recipe + SHA-256 of tagged artifact; not upstream-demo IDs |
| **3** | Mint-route inventory + hardcap design on **that** pin | Open | Every mint path listed; cap keeper design + offline tests; still testnet-only |
| **4** | Genesis allocation freeze (public addresses only) | Open | Worksheet filled; supply audit + preflight pass on candidate genesis |
| **5** | Multi-host **testnet** (not mainnet) | Open | ≥4 independent hosts; recovery drills; public RPC with rate limits |
| **6** | Operator attestations | Open | Separate custody; signed genesis+binary digests; no shared keys |
| **7** | External security + legal review | Open | Written reports on pinned hashes; disclosures distinguish PRVI / TEST / BNB PRIV |
| **8** | Explicit GO record | Open | Named approvers, UTC plan, rollback policy — only after 0–7 |

## Already landed (engineering, not launch)

- Fail-closed `pop_mainnet_guard.py`, `mainnet_gate.py`, launch gate docs
- Genesis allocation worksheet (unfilled) + supply audit tooling
- PoP research stack: engine, locks, round machine, message bus, latency metrics, worker_threads bus
- CI: `.github/workflows/privi-pop-research-safety.yml`
- Validator failure/recovery **test plan** (manual drills; not yet multi-host evidence)
- Launch blockers review (2026-11-25)
- Launch readiness scorecard (`launch_readiness_scorecard.py`) — always reports NO-GO
- Candidate binary pin verifier (`candidate_binary_pin.py`) against `cosmos/evm@v0.7.3` — artifact hash still **UNPINNED**

## Next concrete builds (do in order)

1. Produce a disposable testnet `evmd` and replace `UNPINNED` with its SHA-256. Do not mark it production.
2. **Mint-route inventory** against that pinned tree (no silent bank mint).
3. **Automate recovery smoke** — scripted failure against a local demo only.
4. **Fill genesis worksheet** with public addresses when operators exist; run audits offline.
5. Keep scorecard in CI — never treat artifact counts or a pin match as gate clearance.

## What “launch” requires (reminder)

Independent PoP BFT in a real node binary, SDK-persisted PRVI hard cap, signed genesis, four independent operators, public testnet proof, security audit, legal sign-off, and an explicit GO record. Until then: **build, test, refuse activation**.
