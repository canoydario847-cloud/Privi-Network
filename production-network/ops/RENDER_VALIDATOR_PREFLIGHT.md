# Render hosting — Privi production-validator preflight (NOT DEPLOYED)

**Decision recorded 2026-10-20:** Privi's owner selected **Render** as the *preferred* production validator hosting provider, subject to proof that the proposed architecture meets the security, quorum, P2P connectivity, signer isolation, and disaster-recovery launch gates. This is a deployment **plan**, not evidence of infrastructure, custody, finality, token issuance, public endpoints or mainnet readiness.

## Candidate topology

- Four independently configured, paid **Render private services**, ideally in distinct failure domains; one `priv_validator_key` / remote signing identity per service, **never shared or cloned**. Do not use a Render autoscaled service to represent multiple validators, especially not with attached disk.
- Exactly one independently sized **persistent SSD volume** per service, mounted at the chain data directory. Treat all paths outside the mounted path as **ephemeral**. Each service should be pinned to one audited immutable custom-node binary and the same signed genesis hash.
- Bind CometBFT P2P only to the intended private network. Use protected sentry nodes / external authenticated gateways for client RPC; don't expose validator consensus or signing ports to the open internet. Distinct validator signer ID, block-state disk, and operational authorization per service are required.
- If the four Render private services use the same region, Render's private networking supports direct same-region peer connections. **This is shared regional outage risk, NOT four independent fault domains.** Before financial GO, prove resilience against a provider-wide or region-wide outage (independent region plus an audited secure overlay, or another reviewed fault-separation design). Do not assert cross-region private connectivity exists by default.
- A disk is bound to one instance and **disables zero-downtime deploys**. Roll validator upgrades one service at a time only while the remaining validators retain >2/3 voting power; independently demonstrate no double-sign after restart, delayed deployment, rescheduling or rollback.

## Render limitations that must be demonstrated, not assumed

1. **Networking:** Render private services accept connections from services in the **same workspace and region**. Cross-region CometBFT P2P needs separately audited connectivity. Verify actual P2P TCP reachability, persistent peer IDs, peer authentication, and network partitions. Confirm routing and firewall policy, not just HTTP health checks.
2. **Storage:** persistent disks exist only with eligible paid services; outside-mount files are wiped during restart; disks cannot attach to >1 service instance. Configure single-writer storage and test recovery from daily disk snapshots. Verify validator state data and signer high-watermark files are on durable storage where required, with anti-rollback controls.
3. **Deployment:** a disk-backed service is stopped during each deployment, causing downtime. Disable *automatic production deploys*. Require manual signed and checksummed release rollout, coordinated upgrades and post-upgrade peer/finality monitoring.
4. **Signer security:** Render environment variables and application disks are **not independently audited HSMs**. Prefer per-validator external remote signers/HSMs or equivalent risk-reviewed custody with mutually authenticated connections, strict key backup and no startup scripts that share keys. Do not put secrets into git, images, CI, Render Blueprint files, application logs, or chats.
5. **Operations:** separate monitoring and log sinks, slash/double-sign alerting, static binary checksums, chain-ID and genesis SHA checks, sentry isolation, backup restores and controlled loss/recovery of any one validator. A successful Render status is **not** proof of CometBFT quorum.

## Preflight evidence required for EACH of four candidate services

| Evidence field | Status |
| --- | --- |
| Render service instance ID, workspace and region (not a secret) | UNVERIFIED |
| Unique consensus public key and CometBFT node ID; independent signer | UNVERIFIED |
| SHA256 of exactly matching genesis and signed binary | UNVERIFIED |
| Disk persistence, single-writer rules, backup and restart drill | UNVERIFIED |
| Actual P2P TCP peers, quorum vote, block hash, sync and restart | UNVERIFIED |
| Protected signer custody, double-sign prevention and upgrade controls | UNVERIFIED |
| Fault-domain assessment against host + region-wide loss | UNVERIFIED |

**Current verification: 0 / 4 financial production validators.** The valueless upstream disposable four-validator GitHub test and existing Railway test services do not fulfill Render production verification.

## References (provider documentation)

- [Render persistent disks](https://render.com/docs/disks)
- [Render private services](https://render.com/docs/private-services)
- [Render private networking](https://render.com/docs/private-network)
- [Render platform maintenance](https://render.com/docs/platform-maintenance)
- [Render deployments](https://render.com/docs/deploys)

**NO-GO for financial launch** until signed PRVI genesis/release, audited native PoP EVM state transitions, external security review, and all owner-controlled production-validator checks pass. No deployment or secret/key creation is authorized by this document.
