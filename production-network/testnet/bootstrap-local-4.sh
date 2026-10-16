#!/usr/bin/env bash
# Official Cosmos EVM four-node local DEV demo; NEVER reuse generated keys publicly.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM="$ROOT/.upstream-evm"
TAG="v0.7.3"
CHAIN_ID="privi-testnet-1"
for tool in git docker make; do
  command -v "$tool" >/dev/null || { echo "Missing $tool" >&2; exit 1; }
done
docker info >/dev/null 2>&1 || { echo "Docker daemon not running" >&2; exit 1; }
if [[ ! -d "$UPSTREAM/.git" ]]; then
  [[ ! -e "$UPSTREAM" ]] || { echo "Unexpected upstream directory exists" >&2; exit 1; }
  git clone --depth 1 --branch "$TAG" https://github.com/cosmos/evm.git "$UPSTREAM"
fi
[[ "$(git -C "$UPSTREAM" describe --tags --exact-match 2>/dev/null || true)" == "$TAG" ]] || {
  echo "Expected pinned upstream tag $TAG" >&2; exit 1;
}
[[ ! -e "$UPSTREAM/.testnets" ]] || {
  echo "Existing state detected. Refusing to overwrite validator keys." >&2; exit 1;
}
cd "$UPSTREAM"
make localnet-build-env
mkdir -m 700 .testnets
docker run --rm -v "$PWD/.testnets:/data" cosmos/evmd \
  testnet init-files --validator-count 4 -o /data \
  --starting-ip-address 192.168.10.2 --keyring-backend=test \
  --chain-id="$CHAIN_ID" --use-docker=true
docker compose up -d
echo "LOCAL four-validator developer cluster starting."
echo "Comet RPC: http://127.0.0.1:26657"
echo "EVM RPC: http://127.0.0.1:8545"
echo "Do not copy these keys into a public network."
