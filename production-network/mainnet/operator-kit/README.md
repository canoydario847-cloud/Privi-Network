# Privi native PRVI mainnet — independent operator handoff

**STATUS: PRE-DEPLOYMENT TEMPLATE — DO NOT START PRODUCTION OR SEND VALUE.**

This kit is for an **independently controlled validator operator** joining a future, externally audited PRVI mainnet. One host runs one signing validator and one public sentry, but it counts as only **one independent operator**. Do not use seven copies of this kit controlled by one person to claim seven operators.

The existing Railway TEST chain is untouched and forever valueless. This kit cannot operate that chain; never reuse `local-4221`, numeric `262144`, or any devnet genesis or secret.

## 1. Before accepting a contract

Operator and launch coordinator agree upon:
- Public contract, uptime/support SLA, monthly fee, supported geographic region and dedicated cloud account under that operator's control.
- Third-party independence evidence and a distinct signing-key owner. If managed by one commercial company on behalf of several slots, count that company as **one operator**, not one per server.
- Approved network IDs, reproducible audited node binary pinned by immutable container `@sha256` digest, its corresponding published SHA-256, public reviewed genesis and allocation manifest, and signed operational runbook.
- Key protection, incident notification, a recovery rehearsal, immutable signed genesis and distributed validator voting power.
- **No guaranteed investment returns** or resale guarantees. Agreements should address hosting SLA, not a coin price.

## 2. Infrastructure per operator (quote these separately)

- One **dedicated validator** VM or host and one **sentry** VM or isolated security boundary. The included two-container Compose is a **minimum topology template** for one host, not a claim of production fault isolation.
- SSD/NVMe persistent disks with capacity and IOPS sized from benchmarked block state, snapshots, offsite backups, OS updates, disk alerting and encrypted filesystem access controls.
- Independent network/firewall management, DDoS protection for sentry P2P TCP 26656, VPN/private networking between signing validator and sentry, private observability, on-call alerts.
- Hardened signing implementation, ideally audited HSM/remote signer (not supplied by the Compose example). No key export into GitHub, Railway, operator tickets or support chat.
- A different backup/snapshot recovery plan per operator that prevents **double signing**. Never clone active validator signing state to a simultaneously running backup.

**Compose is intentionally disabled by default.** Both services have the `approved-mainnet-launch` profile, which must **never** be activated until the independent signing ceremony and production release review explicitly authorize launch.

## 3. Release image contract

Images must supply a compiled externally reviewed Cosmos EVM Privi application executable at `/usr/local/bin/evmd` and run with uid/gid `1025:1025`. The exact immutable registry digest must be approved with the binary digest. Do not use upstream `cosmos/evmd` reference images, demo genesis, `:latest` tags or CI-only synthetic build artifacts for financial mainnet.

Each operator privately initializes its own new `validator-state` and `sentry-state` with distinct keys and matching *approved* genesis. Do NOT check state directories into GitHub. Full directories are intentionally absent from the repository.

```
production-network/mainnet/operator-kit/
  compose.yaml             # disabled launch template
  operator_preflight.py    # offline, read-only inspection
  operator.env.example     # unpopulated, not a deployment credential
  validator-state/         # created ONLY by the operator; NEVER commit
  sentry-state/            # created ONLY by the operator; NEVER commit
```

Each node stores Cosmos EVM home files at `<node>-state/config/`:
- `genesis.json` (exact approved SHA-256)
- `config.toml` (CometBFT P2P configuration)
- `app.toml` (RPC disabled on validator/sentry; nonzero `aprvi` gas)
- `node_key.json` (unique P2P identity, protected)
- Only the validator has `priv_validator_key.json`; store under the validator's exclusive control. A reviewed remote signer may replace the file, but **this basic Compose template does not implement remote signing**.

Preconfigure validator `p2p.pex=false`, trusted `persistent_peers`, `private_peer_ids` and no published RPC ports. Sentry uses `p2p.pex=true`, public P2P only, no private validator signing key. Its P2P connections must include trusted validator peers. The private bridged Docker network restricts direct validator egress; verify full network reachability and peer isolation separately on a nonproduction rehearsal.

## 4. Privately inspect (without transmitting signing keys)

Run using Python 3.11+ on the **operator machine**. Values below must come from an independently approved and signed release manifest; placeholders are not valid:

```bash
python3 operator_preflight.py \
  --state-root . \
  --approved-genesis-sha256 "$APPROVED_GENESIS_SHA256" \
  --cosmos-chain-id "$PRIVI_COSMOS_CHAIN_ID" \
  --evm-chain-id "$PRIVI_EVM_CHAIN_ID" \
  --image-ref "$PRIVI_NODE_IMAGE"
```

The check reads genesis and config only, tests key-file presence and permissions (never prints key material), checks non-demo network IDs and `aprvi` fixed supply. It must FAIL when there is no finalized genesis or confidential keys.

For approved future launch only, and only after audited runbooks and third-party review, use the operator's own `PRIVI_NODE_IMAGE` and `PRIVI_P2P_BIND_ADDRESS` environment and **explicitly** select the `approved-mainnet-launch` Compose profile. Do not enable it as part of vendor application or price negotiation.

```bash
# DRY REVIEW ONLY; DOES NOT START THE NETWORK:
docker compose -f compose.yaml config --services
# Actual launch command deliberately omitted pending signed release authorization.
```

## 5. Sign the genesis ceremony (public attestation only)

Coordinator provides one frozen `genesis.json`, exact audited node binary and the operator registry containing their **public** key and contact evidence. Operators should generate their own *separate* Ed25519 attestation private key offline, sign the **canonical payload** from `ceremony_verify.py --write-signing-payload`, and submit only the signature and public attestation key. No private keys ever go to the coordinator or GitHub.

Signing is only proof of agreement with specified hashes; it does NOT itself validate the source or grant launch authorization. An independent human review must confirm real operator ownership and non-collusion.

## 6. Production monitoring & acceptance

Require liveness via independent checks of CometBFT commit signer set and Ethereum RPC `eth_chainId`, `eth_blockNumber`, `eth_getBlockByNumber`, plus transaction receipts, gas prices, fee handling, state roots, staking, governance, disk health, process restarts, rollback/recovery rehearsals and no double-sign events.

A vendor is ready for payment only after giving a written quote with:
- operator identity, independent infrastructure proof, region/provider;
- uptime SLA, support and on-call escalation;
- estimated monthly price **including compute/storage/network/backups/security**;
- key-custody method, recovery procedure and audit evidence;
- cancellation terms and explicit responsibility for upgrades and incident handling.

## What remains deliberately NOT provided

This package does not contain funded accounts, a usable production genesis, real validator keys, an audited node release, a configured public RPC, a working multisig vault, rewards escrow, an active network or a real PRVI coin. Provisioning or paying operators before those are finalized would create unnecessary expense and security risk.


## Release attestation automation (operator details can come later)

The mainnet-preparation branch now includes `ceremony_verify.py`.
No operator information or real signing keys are required to prepare the
software. The template `release.template.json` contains no final IDs
or hashes and is intentionally rejected until completed. The
`attestations.template.json` file is unsigned and must fail.

Once the **audited final** genesis, allocation ledger and binary are frozen,
publish their three real SHA-256 hashes and the externally accepted chain IDs
in a separate reviewed release JSON. Only then, operators work locally:

```bash
# The private signing operation is performed OFFLINE by the operator, using
# their OWN unrelated Ed25519 attestation private key.
python3 ceremony_verify.py --release /secure/reviewed-release.json \
  --operator-id OPERATOR_PUBLIC_ID \
  --consensus-pubkey OPERATOR_PUBLIC_CONSENSUS_KEY_HEX \
  --write-signing-payload /secure/my-genesis-approval.payload.json

# Coordinator gets public signed attestations ONLY (never signing secrets),
# and verifies their cryptography against the reviewed public operator roster.
python3 ceremony_verify.py --release /secure/reviewed-release.json \
  --roster /secure/reviewed-public-operator-roster.json \
  --attestations /secure/all-signed-operator-attestations.json
```

`ceremony_verify.py` uses the \`cryptography\` Ed25519 verifier and
refuses altered hashes, duplicated public attestation keys, malformed operator
IDs, mismatched consensus public keys and missing signatures. It DOES NOT
certify operator independence, release audits, or on-chain deployment.

**No real operator private signing keys, recovery mnemonics or Railway TEST
bootstrap keys should ever be shared or committed to GitHub.**

