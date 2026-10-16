#!/usr/bin/env bash
# Verify seven ACTUAL self-operated CometBFT validator signers and EVM RPC.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
COMPOSE="$ROOT/.upstream-seven-evm/docker-compose.privi-seven.yml"
[[ -f "$COMPOSE" ]] || { echo "Seven-node Compose file missing. Run bootstrap-seven.sh first." >&2; exit 1; }
python3 "$HERE/audit_seven.py"
python3 "$ROOT/testnet/evm_smoke.py" --rpc http://127.0.0.1:8545 --expect-chain 262144
echo "Seven consensus validators signed the same finalized block. DEV TEST only; not a production PRVI launch."
