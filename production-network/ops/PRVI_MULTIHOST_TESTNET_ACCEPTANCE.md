# PRVI multi-host testnet acceptance plan

**Status: NOT EXECUTED. Financial mainnet: NO-GO.** This plan does not authorize deploying financial PRVI, changing running services, or creating production keys.

## Scope and isolation

- Use **valueless test assets only**. TEST must remain permanently valueless; BNB PRIV and proposed native financial PRVI are separate.
- Use four hosts across distinct failure domains and, where feasible, independent operators. Four local processes on one GitHub Actions runner are **not** a multi-host testnet.
- Pin the reviewed source commit, SDK/Cosmos EVM versions, binary checksum, chain ID, numeric EVM chain ID, testnet genesis checksum, and per-host node IDs. Record all in a signed manifest. Never place keys or mnemonics in the repository.
- Establish sentry topology, peer allowlists, rate-limited RPC, metrics, logs, disk and memory alerts, backups, and an operator on call before any public exposure.

## Required functional and adversarial evidence

| ID | Test | Evidence required | Acceptance |
| --- | --- | --- | --- |
| T01 | Four distinct hosts join identical genesis | Signed manifest, chain IDs, genesis SHA-256, host topology, peer and height snapshots | All nodes converge on one block hash at sampled finalized heights |
| T02 | Native PRVI issuance restrictions on **valueless isolated test state** | Before/after committed bank supply and account balances; rejected mint tx and ABCI response | Unauthorized mint fails; no supply or balance change |
| T03 | Failed transaction atomicity | Controlled SDK cached-context transaction that writes a test balance then errors; before/after committed state root and bank balance | Error response; no persisted partial state or cap record |
| T04 | Genesis rejection | Oversupply, balance/supply mismatch, repeated InitGenesis, wrong staking/EVM denom and enabled ERC20 registration | Each rejected before committed state mutation |
| T05 | Cross-module bypass review | Bank, mint, staking, distribution, EVM, ERC20, IBC, governance, upgrade and migration route inventory | No unauthorized native issuance route; unresolved route blocks release |
| T06 | Validator failover | Stop one validator; restore from approved backup on new host | Remaining validators finalize; restored node catches up without double-sign |
| T07 | Network partition | Controlled isolation of minority peers, then recovery | No conflicting finalized history; operators document halt/recovery behavior |
| T08 | Storage/restart recovery | Crash/restart, disk-full rehearsal, snapshot restore and corruption detection | Verified consistent replay, documented RPO/RTO and no double-sign |
| T09 | EVM/RPC and fees | Signed test transactions, fee charging, invalid tx, gas-limit and rate-limit tests | Consistent receipts, bounded resource use, correct fee accounting |
| T10 | Upgrade rollback | Scheduled test upgrade, failed upgrade rehearsal, backup and stop plan | Explicitly reviewed upgrade safety, compatible state, tested recovery |
| T11 | Sustained operation | Multi-day telemetry: height, missed blocks, latency, memory, disk, RPC 5xx, alerts | No unresolved consensus or critical security defect; objective SLOs approved in advance |
| T12 | Independent security review | Audit report, severity tracking, retest results | No open critical/high launch-blocking findings |

## Transaction rollback test design (T03)

Use the actual pinned Cosmos SDK application with a cached SDK context and a deliberately failing test-only message handler. In one transaction, attempt a state write, then return a sentinel error. Query the **committed** state after block finalization, not just an in-memory mock. Compare bank balances, supply metadata, PRVI cap keeper state, and app hash before and after. Also test a panic and a multi-message transaction where a later message fails. If any earlier state mutation persists, block the financial release and investigate context/commit boundaries. Do not introduce a bypass into a public RPC or a production build.

## Evidence collection template

For each T01–T12 record: UTC timestamp, source commit, release checksum, chain/genesis hash, host/operator (nonsecret identifier), command/test harness revision, sanitized logs, before/after state, result, reviewer, issue link, and retest evidence. Keep raw secrets and signing material out of CI logs.

## Launch decision

Passing disposable GitHub CI is a prerequisite, **not** evidence that T01–T12 were executed. Financial mainnet remains NO-GO until multi-host results, independent audits, production validator signatures, final genesis/release hashes, operations and legal review, and explicit named launch approval are recorded in the mainnet launch gate.
