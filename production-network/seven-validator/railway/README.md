# Railway staging adapter for Privi PR #9

**Status: implementation only until real deployed consensus is audited.** This is seven
self-operated **valueless TEST** Cosmos EVM v0.7.3 validators; not PRVI mainnet,
not seven independent operators, not the BNB Chain PRIV token, and not the
existing Railway Cosmos EVM devnet or Privi NOTE service.

## Topology (new, separate Railway project)

- `privi-bootstrap`: a **one-time key/genesis coordinator** with its own persistent
  `/data` volume. Generates seven identities and one shared genesis. It retains
  a copy of all seven private validator keys on its own persistent disk. This
  central custody is acceptable for **disposable staging only**, **never** for a
  financial mainnet or independently operated validators.
- `privi-validator-0` through `privi-validator-6`: one application process and
  **one separate persistent `/data` volume per service**, no other validator's
  signing key in the node's volume; internal CometBFT P2P on 26656 and private
  Comet RPC on 26657. Validator 0 also has the demo EVM RPC on 8545.
- No public domains, no TCP proxies. Railway's `*.railway.internal` private
  network carries P2P and the HTTPS-independent, private HTTP bundle transfer.
  Each validator requires its own >=32-character random bearer secret shared
  only with the bootstrap coordinator. Railway environment variables are not automatically
  sealed by the connector; restrict access, and mark secrets sealed in the dashboard
  where available. Railway private networking encrypts
  traffic; the coordinator must **never** have a public domain.
- The cluster uses Cosmos chain `local-privi-seven-4221` and the upstream demo
  Ethereum chain ID `262144`. Both are disposable; all TEST units valueless.
- The pinned source is `cosmos/evm` v0.7.3 at
  `c3ae9067a7eadcdea55a5192226916deb44c71c4`, built using Go 1.25.9.

## Deploy sequence

1. In the user's existing Railway account, use a **new private project**
   named `Privi Seven Validator Staging` and one environment `staging`.
   Do not connect or edit existing Privi projects.
2. Create EIGHT services named exactly as listed above. Give each ONE
   independent persistent volume mounted at `/data`. Put them all in the
   same Railway region; keep one replica per service.
3. Set `PRIVI_RAILWAY_ROLE=bootstrap` on `privi-bootstrap` and a private
   `PRIVI_BOOTSTRAP_TOKENS_JSON` mapping the keys `"0"` through `"6"` to
   seven **different cryptographically random secrets** of at least 32 chars.
4. On each validator set `PRIVI_RAILWAY_ROLE=validator`, `PRIVI_NODE_INDEX`
   to its index, and `PRIVI_NODE_BOOTSTRAP_TOKEN` to ONLY its matching secret.
   Set `RAILWAY_RUN_UID=0` on ALL eight services: Railway root-mounts volumes,
   while the script explicitly drops the validator process to UID 1025.
5. Connect all eight services to `canoydario847-cloud/Privi-Network`,
   branch `build/privi-seven-validators-20261016`, with
   `dockerfilePath=production-network/seven-validator/railway/Dockerfile`.
   The code is *not* deployable from the default branch as-is.
6. Start the coordinator first. It refuses to reset partial/existing bootstrap
   identities and serves node-specific compressed homes privately.
   Then start the seven validators. Each refuses overwriting an initialized
   home, downloads only its own key on the first boot, and uses its OWN volume.
   Never clear `/data`, reset node state, or deploy two replicas of one signer.
7. Inspect deployment status and logs. To prove real consensus, run
   `production-network/seven-validator/audit_seven.py` **from within the
   private network**, passing the seven URLs
   `http://privi-validator-N.railway.internal:26657` using `--rpc` seven times.
   Require exactly seven signed commits, same chain/genesis, >2/3 power, and
   verified `eth_chainId=262144` before calling staging **running**.
   A green GitHub CI run alone never proves the Railway cluster is live.
8. Set backups/restore and stop policy before long-lived testing.
   The bootstrap volume contains all seven test signing keys; safeguard it.
   On a failed first bootstrap, do **not** delete partial state and rerun.

### Cost and safety

Eight continuously running Railway services, builds and volumes may incur
significant usage charges. Keep this project separate and verify quota/cost
before committing staged infrastructure. The bootstrap is an **additional**
coordinator service; this is still only seven consensus validators.

No wallet payouts, PRVI genesis, PRVI financial mainnet, bridges, live
liquidity, or token supply changes are performed by this adapter.

### Offline verification

```bash
python3 -m unittest discover -s production-network/seven-validator/railway -p 'test_*.py' -v
python3 -m py_compile production-network/seven-validator/railway/main.py
```

### Safety limitation

The bootstrap retains all seven private testnet signing keys so this setup
does NOT satisfy independent-validator custody, decentralization, or a
production-mainnet security review. A production design would use independently
operated nodes and separately generated keys, with no shared coordinator.
