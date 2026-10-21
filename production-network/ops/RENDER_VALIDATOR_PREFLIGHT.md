# Render hosting — Privi production-validator preflight (NOT DEPLOYED)

**Decision recorded 2026-10-20:** Privi's owner selected **Render** as the *preferred* production validator hosting provider, subject to proof that the proposed architecture meets the security, quorum, P2P connectivity, signer isolation, and disaster-recovery launch gates. This is a deployment **plan**, not evidence of infrastructure, custody, finality, token issuance, public endpoints or mainnet readiness.

## Connected Render workspace read-only inspection — 2026-10-20

A direct provider service-list inspection of the connected Render workspace found
**13 existing services**, none of type `private_service`, `background_worker`,
or a recognizable CometBFT validator. The inspected inventory consists of
eight `static_site` services and five `web_service` instances.
In particular:

- `privi-ledger`, `privi-anchor`, `privi-verify`: **public web services**
  (not blockchain validator nodes), each on Render's Virginia region on
  a starter plan, each with its own 1 GB persistent disk mounted at `/data`.
  Their deployed source paths point to HTTP application servers, not the
  reviewed custom Privi node binary. They auto-deploy from repository `main`
  and show a publicly reachable web service URL; **do not reassign or
  repurpose them to sign consensus**.
- `privi-discovery`: public free-tier Python web service in Ohio, not a
  validator. `jose-backend`: public free-tier Node web service in Oregon,
  not a validator.
- Eight additional `privi-*` or website `static_site` projects run public
  sites; static sites cannot host a running consensus signer.

This read-only provider inventory **does not demonstrate current service
health, chain finality, custody of keys, reserve capacity, HSM capability or
ownership of production signing identities**. It establishes only that the
connected Render account is usable and that **no production Privi validator
candidate is present among the listed services**: 0/4 verified. The existing
public Privi web apps may remain available independently of blockchain launch.
Do not migrate these services or disable auto-deploy in this planning stage.

The existing connector tools can list services, inspect metrics/logs and
create public web services; they **do not expose creation of a Render private
service, paid persistent-disk attachment to a new service, or HSM custody**.
Those operations require a separately reviewed deployment workflow and
provider permissions, not an assumption that a public web service is suitable.

## Offline deployment candidate and provider-identity preflight

The reviewed, **non-deploying** handoff files are:

- [Four private-validator candidate slots](render-validator-candidates.NONLIVE.json).
- [Read-only Render provider checker](render_validator_preflight.py).
- [Fifteen adversarial preflight tests](test_render_validator_preflight.py).

Each proposed signer has one named service slot, unique public signer fingerprint,
intended region and fault domain, persistent disk at `/data`, single instance,
Docker runtime and **manual-deploy-only** policy. All actual service IDs, keys,
signed release digests and independent security attestations intentionally
start as `UNASSIGNED`. Do not put mnemonics, private keys, seed material,
provider API tokens or remote-signer credentials in these files.

Run locally, from the repository root, to verify the candidate **structure**:

```bash
python3 production-network/ops/render_validator_preflight.py \
  production-network/ops/render-validator-candidates.NONLIVE.json --mode draft
python3 -m unittest discover -s production-network/ops -p 'test_render_validator_preflight.py'
```

Once four genuine **private** services have been provisioned separately by
approved operators, export their **sanitized read-only** Render `list_services`
JSON response to a file *outside git*, e.g. `/tmp/render-services.json`.
Only then, after separately reviewing public service IDs and fingerprints,
fill in the candidate metadata and compare provider reality:

```bash
python3 production-network/ops/render_validator_preflight.py \
  /tmp/approved-render-candidate.json --mode observe \
  --render-services /tmp/render-services.json
```

The command rejects, among other things, a web service misrepresented as
a private validator, a mismatch between Render workspace IDs, enabled auto
deploy, free compute, Docker/runtime mismatch, absent/undersized/reused
persistent disks, more than one service instance per signer, wrong regions,
or reused consensus public-key fingerprints. It also refuses malformed or
duplicate-key JSON and credential-like secret fields.

**Important:** `observe` and `production` always exit **3 (NO-GO)** even
when metadata appears to match four hypothetical services. They cannot
verify signer custody, authenticated cross-region networking, genesis,
binary integrity, key high-watermark monotonicity, BFT safety/liveness,
independent audits or human launch approvals. Exit 0 from `draft` only
means the manifest structure is valid. This is a release candidate
*preflight*, not an executable validator daemon, Render Blueprint, funded
hosting order, or a mainnet activation script.

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
