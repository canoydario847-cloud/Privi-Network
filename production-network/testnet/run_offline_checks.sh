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
# The 1B PRVI genesis allocation worksheet is UNSIGNED and does not mint.
# Refuse any release flow that mistakes it for a live financial genesis.
python3 "$ROOT/ops/verify_prvi_issuance_plan.py" "$ROOT/ops/prvi_issuance_plan.UNSIGNED.json" --mode draft
if python3 "$ROOT/ops/verify_prvi_issuance_plan.py" "$ROOT/ops/prvi_issuance_plan.UNSIGNED.json" --mode launch; then
  echo "FATAL: unsigned PRVI allocation worksheet authorized live mint" >&2
  exit 1
else
  status=$?
  if [[ "$status" -ne 3 ]]; then
    echo "Unexpected issuance preflight result $status" >&2
    exit 1
  fi
fi
# Verify the June 2026 Oracle Always Free CPU, RAM, storage and NO-SPEND policy.
python3 "$ROOT/ops/oracle_free_pilot_preflight.py" "$ROOT/ops/oracle-always-free-pilot.candidate.json"
# The founder's public EVM wallet must be the ONLY proposed control wallet.
# Verify the owner policy, but explicitly prove it NEVER authorizes launch.
python3 "$ROOT/ops/verify_privi_single_owner.py" "$ROOT/ops/privi_owner_wallet.candidate.json" --mode draft
if python3 "$ROOT/ops/verify_privi_single_owner.py" "$ROOT/ops/privi_owner_wallet.candidate.json" --mode launch; then
  echo "FATAL: draft founder wallet manifest authorized real financial mainnet" >&2
  exit 1
else
  status=$?
  if [[ "$status" -ne 3 ]]; then
    echo "Owner wallet launch guard returned unexpected code $status" >&2
    exit 1
  fi
fi
# Owner-operated financial validators are a non-live, secret-free candidate.
# Accept the four-node draft structure, but prove launch preflight NEVER passes.
python3 "$ROOT/ops/owner_validator_preflight.py" "$ROOT/ops/owner-operated-validators.candidate.json" --mode draft
if python3 "$ROOT/ops/owner_validator_preflight.py" "$ROOT/ops/owner-operated-validators.candidate.json" --mode preflight; then
  echo "FATAL: incomplete owner-operated validator manifest passed production launch preflight" >&2
  exit 1
else
  status=$?
  if [[ "$status" -ne 3 ]]; then
    echo "Owner validator preflight returned unexpected status $status" >&2
    exit 1
  fi
fi
# Render validators are a secret-free NONLIVE candidate, not a deployment.
# The provider-facing checker refuses web services masquerading as BFT signers.
python3 "$ROOT/ops/render_validator_preflight.py" \
  "$ROOT/ops/render-validator-candidates.NONLIVE.json" --mode draft
if python3 "$ROOT/ops/render_validator_preflight.py" \
  "$ROOT/ops/render-validator-candidates.NONLIVE.json" --mode production; then
  echo "FATAL: candidate Render topology authorized mainnet" >&2
  exit 1
else
  status=$?
  if [[ "$status" -ne 3 ]]; then
    echo "Render validator production guard returned unexpected status $status" >&2
    exit 1
  fi
fi
node --check "$ROOT/ops/legacy_state_copy.js"
node --test "$ROOT/ops/test_legacy_state_copy.js"
node --test "$ROOT/ops/test_verify_operator_attestations.cjs"
node --test "$ROOT/testnet/test_send_disposable_test_transfer.cjs"
node --test "$ROOT/testnet/test_deploy_disposable_counter.cjs"
# Point of Position (PoP) logical-stamp signature/sequence/hash prototype.
# This verifies offline records; it is NOT a native PoP BFT consensus engine,
# does not prove economic valuation and cannot authorize financial launch.
(cd "$ROOT/mainnet/pop" && GOTOOLCHAIN=local go test -mod=mod -count=1 ./...)
# Hard-cap reference is a pure-Go OFF-CHAIN accounting model, not deployed
# Cosmos SDK consensus code. Race tests exercise simultaneous candidate mints.
command -v go >/dev/null
(cd "$ROOT/mainnet/capmodel" && GOTOOLCHAIN=local go test -race -count=1 ./...)
# Strict AST baseline for pinned Cosmos EVM v0.7.3 mint entry points.
(cd "$ROOT/mainnet/mintscan" && GOTOOLCHAIN=local go test -race -count=1 ./...)
python3 -m unittest discover -s "$ROOT/mainnet/custom-app" -p "test_*.py"
# Provider-observed Railway TEST services are *not* production validators.
# Fail if snapshot is invalid or if production preflight ever permits TEST.
python3 "$ROOT/ops/railway_staging_preflight.py" "$ROOT/ops/railway_staging_observation.json" --mode staging
if python3 "$ROOT/ops/railway_staging_preflight.py" "$ROOT/ops/railway_staging_observation.json" --mode production; then
  echo "FATAL: disposable Railway TEST services authorized financial mainnet" >&2
  exit 1
else
  status=$?
  if [[ "$status" -ne 3 ]]; then
    echo "Railway financial preflight returned unexpected status $status" >&2
    exit 1
  fi
fi
bash -n "$ROOT/testnet/bootstrap-local-4.sh"
echo "Offline checks passed. Live EVM / CometBFT testing still required."
