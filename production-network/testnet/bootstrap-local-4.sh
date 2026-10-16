#!/usr/bin/env bash
# Official Cosmos EVM four-node local DEV demo; NEVER reuse generated keys publicly.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM="$ROOT/.upstream-evm"
TAG="v0.7.3"
CHAIN_ID="local-4221"
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
# The upstream Compose file exposes all RPC/P2P ports on every host interface.
# For a local developer demo, rewrite published port bindings to loopback only.
# This generated file is never committed and must never overwrite an existing file.
SAFE_COMPOSE="$UPSTREAM/docker-compose.localhost.yml"
[[ ! -e "$SAFE_COMPOSE" ]] || { echo "Local Compose override already exists" >&2; exit 1; }
sed -E 's/^([[:space:]]*- )"([0-9]+(-[0-9]+)?):/\\1"127.0.0.1:\\2:/' docker-compose.yml > "$SAFE_COMPOSE"
if grep -E '^[[:space:]]*- "[0-9]+(-[0-9]+)?:' "$SAFE_COMPOSE"; then
  echo "Unsafe published port detected" >&2; exit 1
fi
docker compose -f "$SAFE_COMPOSE" up -d
echo "LOCAL four-validator developer cluster starting."
echo "Comet RPC: http://127.0.0.1:26657"
echo "EVM RPC: http://127.0.0.1:8545"
echo "Do not copy these keys into a public network."
