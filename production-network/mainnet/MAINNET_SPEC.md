# Privi Mainnet — gated technical specification (PRVI)

**STATUS: NOT DEPLOYED. NO MINTING OR FINANCIAL ACTIVATION AUTHORIZED.**

This document describes a proposed real mainnet, **not** the live Railway Privi NOTE prototype, Cosmos EVM upstream developer chain, or existing BNB Chain PRIV token. The demo network's default known keys, numeric EVM chain ID 262144, and `local-4221` genesis MUST NOT be imported into mainnet.

## Approved high-level choices

- Native coin ticker: **PRVI** (distinct from the existing BNB Chain PRIV token).
- Supply cap: **1,000,000,000 PRVI**, 18 decimals = **1,000,000,000,000,000,000,000,000,000** smallest units.
- Proposed minimum denomination: `aprvi` (1 PRVI = 10^18 aprvi); finalize implementation, display metadata and gas denomination before genesis.
- Mainnet should implement meaningful on-chain utility: native gas, staking and slashing, and auditable fees for permissionless applications and signed IoT event anchors.
- **TEST must stay valueless and isolated**. BNB Chain PRIV remains on BNB Chain with no assumed exchange rate, claim rights, mint, bridge, or automatic migration.

## Unresolved parameters requiring sign-off

- Unique Cosmos chain ID and independently registered/nonconflicting EIP-155 numerical chain ID. No reuse of `local-4221` or demo numeric `262144`.
- Native production binary source, pinned full Go dependency tree/SBOM, upgrade plan, reviewed app configuration, parameter overrides, genesis creation tooling, chain-ID bindings and checksum.
- **Actual genesis allocation ledger**: every account, purpose, amount, vesting, treasury signers, staking/rewards escrow and public reconciliation. All created genesis balances and reserves must sum to **exactly** the fixed 1 billion cap. No undisclosed extra minting, inflation, or bypass of supply-cap invariants.
- Precise issuance and vesting schedules, staking APR and reward source, fee routing, governance quorum, vote period, slashing, unbonding and emergency powers. These have not been approved.
- Holder rights/disclosures, exchange eligibility, data privacy and financial regulatory assessment by qualified counsel.

## Validator minimums

1. At least **seven independently operated validators** with different real operational control (not seven containers in one Railway account). Different funding sources or LLC shells under shared control do not count as independent.
2. Operators generate, keep and back up consensus signing keys **outside GitHub, CI, developer containers and logs**. Never repurpose upstream demo keys. Prefer audited remote signers/HSMs and enforce no-double-sign fencing.
3. Each operator signs off on a common reviewed genesis SHA-256, binary digest and agreed chain IDs, then independently validates these before block one.
4. Operators provide a public consensus key, public network identity and verifiable operator commitment; no private keys or recovery phrases in the registry.
5. No individual operator controls >= 1/3 voting power; plan for >2/3 live voting power despite one planned maintenance/outage, then verify empirically.
6. Distribute machines and sentries across independent cloud operators, geographical regions and routing providers; do not concentrate validator safety in a single project/region.
7. Validators expose only hardened P2P/sentry links; public EVM JSON-RPC and CometBFT RPC run on dedicated non-signing gateway nodes protected by access policy, TLS, rate limits and DDoS defenses.

## Genesis requirements

- Reviewed network IDs, fee denomination, supply cap and genesis-time bond allocations. Compare total bank supply with the reviewed account manifest; reject any unaccounted supply or zero-value bridge liabilities.
- Publish SHA-256 for final canonical genesis JSON, binary commit and reproducible build artifact. Collect independent cryptographic signoffs from each operator.
- Preconfigure governance safety (timelocked upgrades, emergency powers limited in scope, vote timelocks), slashing and staking invariants; test recovery without double-signing.
- Allocations to contributor and treasury accounts must have disclosed on-chain enforcement mechanisms, audited vesting / escrow and documented beneficial ownership.
- Never initialize live state or validator keys using `evmd testnet init-files` defaults; use a purpose-built reviewed generator and dry-run ceremony.

## Mainnet launch gates — all blocking

- [ ] Reviewed Privi-specific Cosmos EVM release; independent security audit of chain code and dependencies; critical/high findings remediated.
- [ ] Independent audit of native coin economics, supply-cap enforcement, vesting, genesis tooling, and governance permissions.
- [ ] Verified and reserved unique Cosmos/EVM chain IDs, native denomination and genesis manifest summing exactly to the approved fixed supply.
- [ ] Seven genuine independent operators with public keys, separate secure key custody, signed genesis, operations contacts and complete runbooks.
- [ ] Separately deployed sentries and non-signing RPC gateways, monitoring and backup/failover arrangements.
- [ ] Long-running public rehearsal with **valueless** tokens proving staking, governance, contracts, RPC, safety, liveness, isolation, restore, upgrades and double-sign protection.
- [ ] Independent legal/regulatory review for intended distribution, marketing and liquidity.
- [ ] Release sign-off by stakeholders, published documentation, public monitoring, genesis hash and operator signatures.
- [ ] Emergency response rehearsal, supply-invariant monitoring, backups and key recovery tests completed.

**No MAINNET RPC, coin distribution, PRVI mint, token sale, bridge, liquidity pool, trading representation, or public production launch until these conditions are independently verified.**

## Fail-closed readiness tool

Run `python3 production-network/mainnet/mainnet_preflight.py --manifest /secure/nonsecret-mainnet-review.json` to assess a *redacted, signed-off* operator/evidence manifest. The tool validates required fields but **is not a cryptographic signature verifier or an auditor**. Operator attestation signatures and genesis supply must be verified independently before mainnet; passing JSON checks alone NEVER authorizes launching funds or a blockchain.

The example `manifest.example.json` intentionally leaves required information blank and must fail preflight. Never commit real private keys, mnemonic phrases, validator state or secrets.
