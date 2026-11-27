#!/usr/bin/env bash
# Compile the cap-enforced candidate in an isolated checkout for validator testing.
set -euo pipefail
if [[ $# != 1 ]]; then
  echo "Usage: $0 NEW_OUTPUT_DIRECTORY" >&2
  exit 2
fi
output=$(realpath -m "$1")
if [[ -e "$output" ]]; then
  echo "Output directory already exists: $output" >&2
  exit 1
fi
repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
export GOTOOLCHAIN=local
[[ $(go env GOVERSION) == go1.25.9 ]] || { echo "Go 1.25.9 required" >&2; exit 1; }
mkdir -p "$(dirname "$output")"
work=$(mktemp -d "$(dirname "$output")/.privi-build.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
upstream="$work/.upstream-capbuild"
patches="$repo/production-network/mainnet/custom-app"
git clone --quiet --depth 1 --branch v0.7.3 https://github.com/cosmos/evm.git "$upstream"
python3 "$patches/apply_prvi_cap.py" --upstream "$upstream" --source-repo "$repo"
cd "$upstream/evmd"
go mod download github.com/cosmos/cosmos-sdk@v0.54.3
sdk="$work/privi-patched-sdk-app-only"
python3 "$patches/patch_sdk_bank_source.py" --sdk-root "$(go env GOMODCACHE)/github.com/cosmos/cosmos-sdk@v0.54.3" --output-dir "$sdk"
go mod edit -replace="github.com/cosmos/cosmos-sdk=$sdk"
mkdir "$work/result"
go build -p 2 -mod=mod -trimpath -o "$work/result/privi-evmd" ./cmd/evmd
go list -m -json github.com/cosmos/cosmos-sdk > "$work/result/sdk-module.json"
go version -m "$work/result/privi-evmd" > "$work/result/build-info.txt"
python3 "$patches/verify_privi_sdk_binary.py" --module-json "$work/result/sdk-module.json" --build-info "$work/result/build-info.txt" --sdk-dir "$sdk"
(cd "$work/result" && sha256sum privi-evmd > SHA256SUMS)
mv -T "$work/result" "$output"
