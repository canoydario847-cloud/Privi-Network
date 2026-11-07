# Privi Car — owner-controlled edge agent (research prototype)

## Purpose
Opt-in vehicle-adjacent AI agent and edge-compute worker on a companion device or manufacturer-authorized compute environment. **Not** a car ECU modification, autonomous driving controller, or production financial service.

## Security boundaries
- Never access CAN bus, OBD write commands, immobilizer, steering, braking, battery control, firmware update, or vehicle safety systems.
- Vehicle stays operable when agent is disconnected. Owner must consent to each permission; default deny.
- Start with an external companion device and mock telemetry. No unsupported claim of compatibility with every car.
- No computation while driving unless the OEM explicitly certifies safe isolated resources; initial policy: only parked, owner-opted-in, external power, thermally safe.
- Encrypt local data; minimize telemetry; short retention; owner deletion; do not sell raw location or driver data.
- Agent downloads require signed manifests, pinned publisher keys, artifact digest checks, least-privilege sandbox, resource budgets, revocation, and rollback.
- Network jobs must be authenticated, tenant-isolated, rate-limited, replay-resistant, and auditable. Reject jobs when attestation or policy checks fail.

## Reward model
Stablecoins are **not mineable**. A funded, audited rewards pool may compensate verified compute/storage jobs, subject to legal and payment compliance. Do not mint stablecoins or promise passive income. Use simulated, non-transferable test credits until funding and regulatory review.

## Candidate architecture
1. Owner app: enroll/revoke node and view jobs, storage, power use and earnings.
2. Edge worker: sandboxed agent runtime with signed package verification and strict CPU/RAM/disk/network quotas.
3. Broker: mutually authenticated job routing with nonce, expiry, tenant identity and metering.
4. Verifier: deterministic receipts (job digest, device pseudonym, measured resource use, result hash), independent verification before any payout.
5. Settlement adapter: disabled by default; future supported stablecoin transfer from funded pool after review; native PRVI integration separate and gated.

## Initial acceptance tests
- Reject unsigned agent package, tampered digest, expired manifest, revoked publisher, and rollback to vulnerable version.
- Reject job replay, cross-tenant job, expired authorization, and over-quota requests.
- Pause worker on driving, unsafe temperature, low power, or owner opt-out; no vehicle controls exposed.
- Reject reward claims lacking independently verified receipt; no stablecoin creation.

## Rollout gates
Research-only mock-worker -> consented companion-device pilot -> independent security/privacy review -> OEM-specific integration if authorized. No deployment, tokens, payment rails, or vehicle access authorized by this document.
