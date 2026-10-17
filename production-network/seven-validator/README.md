# Privi seven-validator self-operated staging blockchain

**Seven real CometBFT voting validators, controlled by ONE operator, TEST coins only.** Not the financial PRVI mainnet. All seven nodes run on one Linux/Docker host. Their identities and chain state are distinct, but they share one owner and one machine. This architecture cannot provide independent operator fault isolation, so do not market it as seven decentralized mainnet validators.

This project is **completely isolated** from:
- Original JS Privi NOTE prototype on Railway
- Live Cosmos EVM one-validator Railway TEST devnet (`local-4221`)
- Existing BNB Chain PRIV tokens and holders
- Proposed native mainnet PRVI 1,000,000,000-coin configuration in `../mainnet/`

## What is built

| Component | Quantity | Isolation |
| --- | --- | --- |
| CometBFT voting validators | 7 | Individually initialized distinct consensus signing keys |
| Cosmos EVM application process | 7 | One process per Docker container, own `/data/nodeN/evmd` |
| CometBFT RPC | 7 | Published only at `127.0.0.1:26657, 26667, ... 26717` |
| Ethereum JSON-RPC | 1 | Published only at `127.0.0.1:8545` |
| Private node data/state directories | 7 | `production-network/.seven-validator-state/nodeN/evmd`, mounted separately |
| Dedicated Docker bridge network | 1 | `192.168.77.0/24`, peer identities `192.168.77.10` through `.16` |
| Genesis | 1 shared | Disposable new chain `local-privi-seven-4221`, **not** mainnet |
| Ethereum numeric chain ID | 262144 | Upstream example Cosmos EVM v0.7.3. Not a distinct PRVI production chain ID |

The builder pins upstream `cosmos/evm` **v0.7.3**, commit `c3ae9067a7eadcdea55a5192226916deb44c71c4`, with the required Go 1.25.9 Docker build adjustment. This is a disposable TEST staging chain, not a PRVI-denominated chain.

## Run seven nodes (Linux + Docker with Docker Compose v2)

Requires sufficient CPU, RAM and fast disk to operate seven Cosmos EVM nodes simultaneously. Seven on one host are a development/test topology and may exceed smaller free CI runners or desktop machines. No hosting payment is required to generate code.

From the root of the Privi-Network checkout:

```bash
bash production-network/seven-validator/bootstrap-seven.sh

# Wait until consensus has started; check all seven real commit signatures:
bash production-network/seven-validator/verify-seven.sh

# Observe validator status:
docker compose -f production-network/.upstream-seven-evm/docker-compose.privi-seven.yml ps
```

**Safety:** The bootstrap deliberately refuses to overwrite existing state or an existing upstream checkout. It initializes seven disposable keys and never prints initialization seed phrases. The initial setup splits keys into seven **separate bind mounts** so individual containers do not mount their peers' key directories. All seven are nevertheless owned by the same machine operator.

The `production-network/.seven-validator-state/` directory is ignored by Git and must remain on disk across restarts. Never upload it or place any wallet or signing key into GitHub.

## RPC endpoints

| Node | CometBFT RPC |
| --- | --- |
| Validator 0 | `http://127.0.0.1:26657` |
| Validator 1 | `http://127.0.0.1:26667` |
| Validator 2 | `http://127.0.0.1:26677` |
| Validator 3 | `http://127.0.0.1:26687` |
| Validator 4 | `http://127.0.0.1:26697` |
| Validator 5 | `http://127.0.0.1:26707` |
| Validator 6 | `http://127.0.0.1:26717` |

Upstream EVM JSON-RPC: `http://127.0.0.1:8545` (validator 0 only).

The `audit_seven.py` script independently checks seven CometBFT endpoint peer IDs, the same Cosmos chain, block hashes, equal validator voting-power sets, seven distinct consensus addresses and **seven valid commit signatures from the same block**, with >2/3 voting power. The EVM smoke separately checks `eth_chainId`, height and block hash.

## Stop safely

```bash
docker compose -f production-network/.upstream-seven-evm/docker-compose.privi-seven.yml down
```

This command stops/removes running containers but **does not remove the persistent chain state**. To restart an existing initialized seven-node chain safely, without running the guarded one-time bootstrap again:

```bash
docker compose -f production-network/.upstream-seven-evm/docker-compose.privi-seven.yml up -d
```

Do not delete/clone old state blindly, or run two copies of the same validator key simultaneously. A snapshot restore involving a signing validator needs double-sign prevention and a reviewed recovery procedure.

## CI

`.github/workflows/privi-seven-validators.yml` provides:
1. Python unit tests and Bash checks for the exact seven-node Compose configuration, loopback-only RPC, distinct state paths and rejection of incomplete signatures.
2. A disposable GitHub-hosted runner that builds and boots **seven upstream Cosmos EVM** validator containers, verifies actual seven-validator consensus and a working EVM RPC, then stops the containers.
3. No key publishing or artifact upload; ephemeral nodes and TEST tokens have no financial value.

Run the offline tests yourself:

```bash
python3 -m unittest discover -s production-network/seven-validator -p 'test_*.py' -v
```

## Toward eventual PRVI mainnet

Seven self-operated validator *processes* are not independent custody. After successful staging tests, externally audited PRVI mainnet genesis and binaries would require separate production keys, infrastructure/fault domains and operator governance controls. The separate `../mainnet/operator-kit` provides hardened topology templates and seven-operator attestation safeguards. There is no mainnet coin minting, mainnet chain startup, or public PRVI liquidity here.
