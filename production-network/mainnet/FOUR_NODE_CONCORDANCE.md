# Privi four-validator RPC concordance — valueless staging only

**NO FINANCIAL MAINNET, NO ISSUANCE, NO AUTOMATED DEPLOYMENT.** This is a source-controlled runbook for a future four-host private staging test. Privi World Corp would control all four signing hosts; **one operator controlling four validators is not four independently owned operators**.

The [offline four-node observer](../ops/verify_four_validator_observations.py) compares independently captured, read-only RPC responses to catch mismatched network IDs, diverging Comet block hashes, catching-up peers, unexpected EVM chain IDs, duplicate node IDs, duplicate consensus validator addresses, invalid voting power, and invalid snapshot files. It does **not** contact any VPS, access signing keys, verify cryptographic quorum certificates, or authenticate screenshots/RPC payloads. Its result must never authorize a financial launch.

## Prerequisites

- **Four actual, separately hosted** valueless Privi staging nodes, with authenticated administrator access. A single Contabo VPS hosting four containers is not acceptable evidence of four separate failure domains.
- Verified CometBFT RPC `127.0.0.1:26657` and Ethereum JSON-RPC `127.0.0.1:8545` **bound to loopback only**, each on its intended host. No public RPC port opening.
- Individually approved expected Cosmos chain ID and numeric Ethereum chain ID. **Do not copy developer defaults** (`local-4221`, Ethereum `262144`) into a proposed financial launch.
- Capture from trusted shells **on each node**, in an operator-controlled directory (for example `umask 077`); use no credentials or private signing keys.

## Capture each node's read-only observations

On each host, from a trusted console, substitute the corresponding node index (01 through 04), using the owner-approved local staging endpoints:

```sh
umask 077
curl --fail --silent --show-error --max-time 5 \
  http://127.0.0.1:26657/status > node01-comet.json

curl --fail --silent --show-error --max-time 5 \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
  http://127.0.0.1:8545 > node01-eth.json
```

For the other hosts, substitute `node02`, `node03`, `node04`. Gather the eight **nonsecret** captures in a single local directory through an authenticated channel. Review any peer address/ID metadata before sharing. **Do not store passwords, wallet details, private keys, tokens, or captured credentials.**

Because `/status` returns each host's **latest** block rather than a requested historic height, the verifier requires all four captured status replies to show **the exact same height and block hash**. If heights differ during continuous block production, recapture at a stable staging checkpoint or use a separately reviewed height-specific observation technique. **Never infer consensus agreement from different-height hashes.**

## Local bundle (no real signing evidence)

Create `bundle.json` beside the eight captures. Replace **only** the agreed staging chain IDs, not the four fixed validator labels:

```json
{
  "schema_version": 1,
  "purpose": "valueless-four-host-staging",
  "cosmos_chain_id": "privi-stage-not-financial-1",
  "evm_chain_id": 424242,
  "nodes": [
    {"id": "privi-owner-val-01", "comet_status": "node01-comet.json", "eth_chain_id": "node01-eth.json"},
    {"id": "privi-owner-val-02", "comet_status": "node02-comet.json", "eth_chain_id": "node02-eth.json"},
    {"id": "privi-owner-val-03", "comet_status": "node03-comet.json", "eth_chain_id": "node03-eth.json"},
    {"id": "privi-owner-val-04", "comet_status": "node04-comet.json", "eth_chain_id": "node04-eth.json"}
  ]
}
```

The example IDs and test values are fictitious and **not** network launch selections.

```sh
python3 production-network/ops/verify_four_validator_observations.py --bundle /secure/staging-snapshots/bundle.json
```

The tool reads only the local bundle and its eight distinct basename-only JSON snapshots; it rejects symlinked files, duplicate JSON properties, probable credential fields/values, malformed metadata, inconsistent block hashes and node identifiers. The success marker is `FOUR_UNAUTHENTICATED_SNAPSHOTS_CONCUR`, **not `MAINNET_LIVE`**.

## Independent launch checks still mandatory

A consensus snapshot is only a reported state. To claim a reliable staging network, separately record verified host identities, same signed genesis SHA-256, protected distinct consensus signer keys, CometBFT validator set and >2/3 signatures/commit proofs at a fixed height, common binary/source release hashes, synchronization and failover/recovery tests, screened network exposure, verified provider fault-domain separation, and an independent security review.

Current Contabo Cloud VPS 6 access remains provider-dependent; the staging branch is [PR #18](https://github.com/canoydario847-cloud/Privi-Network/pull/18). This verifier is tracked on [PR #17](https://github.com/canoydario847-cloud/Privi-Network/pull/17). **Neither branch is deployed or financially live.**
