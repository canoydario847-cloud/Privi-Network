# Candidate binary pin (testnet only)

**Status: PIN_INCOMPLETE. Financial mainnet remains NO-GO.**

Stage 2 of [PATH_TO_LAUNCH.md](PATH_TO_LAUNCH.md) freezes *which* `evmd` a future testnet may run. It does not publish that binary and does not clear launch gate 1.

## Frozen inputs

| Field | Value |
| --- | --- |
| Upstream | `cosmos/evm` tag `v0.7.3` commit `c3ae9067a7eadcdea55a5192226916deb44c71c4` |
| Go | `1.25.9` |
| SDK | `v0.54.3` |
| Artifact name | `evmd` |
| Artifact SHA-256 | **`UNPINNED`** in [candidate_binary_pin.UNPINNED.json](candidate_binary_pin.UNPINNED.json) |
| Scope | `testnet-candidate-only` |

## Refusals

[candidate_binary_pin.py](candidate_binary_pin.py) rejects:

- `financial_mainnet`, `production_release`, or `mainnet_activated` other than `false`
- Cosmos chain IDs that are not `privi-testnet-<name>`, including demo `local-4221` and names that look like mainnet
- EVM chain IDs `1`, `56` (BNB), and demo `262144`
- Any upstream commit other than the pinned `v0.7.3` SHA
- A set SHA-256 that does not match the file passed as `--binary`

A match still prints `financial_mainnet_authorized=false`.

## Commands

```bash
python3 production-network/ops/candidate_binary_pin.py \
  --pin production-network/ops/candidate_binary_pin.UNPINNED.json
# expected: exit 1, PIN_INCOMPLETE

python3 -m unittest -v production-network/ops/test_candidate_binary_pin.py
```

When a disposable testnet build exists, replace `UNPINNED` with the lowercase SHA-256 of that `evmd` and re-run with `--binary`. Do not tag it as a production release.
