#!/usr/bin/env bash
# Offline code sanity/unit tests. Does NOT spin up a real EVM consensus cluster.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v python3 >/dev/null
command -v node >/dev/null
python3 -m py_compile "$ROOT"/testnet/*.py "$ROOT"/migration/*.py "$ROOT"/ops/*.py
(cd "$ROOT/testnet" && python3 -m unittest discover -v -p 'test_*.py')
(cd "$ROOT/migration" && python3 -m unittest discover -v -p 'test_*.py')
(cd "$ROOT/ops" && python3 -m unittest discover -v -p 'test_*.py')
node --check "$ROOT/ops/legacy_state_copy.js"
node --test "$ROOT/ops/test_legacy_state_copy.js"
node --test "$ROOT/ops/test_verify_operator_attestations.cjs"
node --test "$ROOT/testnet/test_send_disposable_test_transfer.cjs"
node --test "$ROOT/testnet/test_deploy_disposable_counter.cjs"
# Hard-cap reference is a pure-Go OFF-CHAIN accounting model, not deployed
# Cosmos SDK consensus code. Race tests exercise simultaneous candidate mints.
command -v go >/dev/null
(cd "$ROOT/mainnet/capmodel" && GOTOOLCHAIN=local go test -race -count=1 ./...)
bash -n "$ROOT/testnet/bootstrap-local-4.sh"
echo "Offline checks passed. Live EVM / CometBFT testing still required."
