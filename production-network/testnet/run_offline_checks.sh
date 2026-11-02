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
node --test "$ROOT/ops/test_verify_operator_release.cjs"
node --test "$ROOT/testnet/test_send_disposable_test_transfer.cjs"
node --test "$ROOT/testnet/test_deploy_disposable_counter.cjs"
# POP tests are OFFLINE RESEARCH ONLY: passing cannot establish native mainnet finality.
node --test "$ROOT"/mainnet/pop_candidate/test_*.cjs
# Hard-cap reference is a pure-Go OFF-CHAIN accounting model, not deployed
# Cosmos SDK consensus code. Race tests exercise simultaneous candidate mints and burns. Repeat to expose\n# schedule-dependent failures; this is still NOT a consensus-level cap proof.
command -v go >/dev/null
(cd "$ROOT/mainnet/capmodel" && GOTOOLCHAIN=local go test -race -count=10 ./...)
# Strict AST baseline for pinned Cosmos EVM v0.7.3 mint entry points.
(cd "$ROOT/mainnet/mintscan" && GOTOOLCHAIN=local go test -race -count=1 ./...)
python3 -m unittest discover -s "$ROOT/mainnet/custom-app" -p "test_*.py"
bash -n "$ROOT/testnet/bootstrap-local-4.sh"
echo "Offline checks passed. Live EVM / CometBFT testing still required."
