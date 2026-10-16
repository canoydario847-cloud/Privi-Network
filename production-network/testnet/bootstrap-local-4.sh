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
# Upstream v0.7.3 requires Go 1.25.9 in BOTH Go modules, but its
# example Dockerfile still uses golang:1.24-alpine.
# Patch only the ephemeral ignored upstream checkout, never our live Railway app.
GO_VERSION="1.25.9"
DOCKERFILE="contrib/images/evmd-env/Dockerfile"
for module in go.mod evmd/go.mod; do
  if ! grep -Fxq "go $GO_VERSION" "$module"; then
    echo "Unexpected Go requirement in $module. Review upstream before building." >&2
    exit 1
  fi
done
OLD_IMAGE="FROM golang:1.24-alpine AS evmd-builder"
NEW_IMAGE="FROM golang:${GO_VERSION}-alpine AS evmd-builder"
if grep -Fxq "$OLD_IMAGE" "$DOCKERFILE"; then
  sed -i "s|^FROM golang:1[.]24-alpine AS evmd-builder$|$NEW_IMAGE|" "$DOCKERFILE"
fi
if ! grep -Fxq "$NEW_IMAGE" "$DOCKERFILE"; then
  echo "Builder Dockerfile changed unexpectedly. Refusing unreviewed build." >&2
  exit 1
fi
echo "Using Go $GO_VERSION builder for Cosmos EVM $TAG"
make localnet-build-env
mkdir -m 700 .testnets
# The upstream image runs as uid/gid 1025:1025. A host-created directory
# belongs to the invoking user and is otherwise inaccessible with mode 0700.
# Fix ownership only for this NEW local developer directory before init-files.
docker run --rm --user 0:0 --entrypoint /bin/sh \
  -v "$PWD/.testnets:/data" cosmos/evmd \
  -c 'chown 1025:1025 /data && chmod 700 /data'
docker run --rm -v "$PWD/.testnets:/data" cosmos/evmd \
  testnet init-files --validator-count 4 -o /data \
  --starting-ip-address 192.168.10.2 --keyring-backend=test \
  --chain-id="$CHAIN_ID" --use-docker=true
# evmd v0.7.3 enables the EVM application mempool. The upstream
# init-files generator sets CometBFT mempool.type=flood, which evmd refuses.
# Amend ONLY these four fresh developer validator configs before booting.
docker run --rm --entrypoint /bin/sh \
  -v "$PWD/.testnets:/data" cosmos/evmd -ec '
  for n in 0 1 2 3; do
    cfg="/data/node${n}/evmd/config/config.toml"
    [ -f "$cfg" ] || { echo "Missing validator $n CometBFT config" >&2; exit 1; }
    grep -q "^\[mempool\]" "$cfg" || { echo "No mempool section: $cfg" >&2; exit 1; }
    sed -i "/^\[mempool\]/,/^\[/ s/^[[:space:]]*type[[:space:]]*=[[:space:]]*\"flood\"/type = \"app\"/" "$cfg"
    sed -n "/^\[mempool\]/,/^\[/p" "$cfg" | grep -Eq "^[[:space:]]*type[[:space:]]*=[[:space:]]*\"app\"" || {
      echo "Invalid EVM mempool config: $cfg" >&2
      exit 1
    }
    echo "Validator $n mempool.type=app"
  done
'
# The upstream Compose file exposes all RPC/P2P ports on every host interface.
# For a local developer demo, rewrite published port bindings to loopback only.
# This generated file is never committed and must never overwrite an existing file.
SAFE_COMPOSE="$UPSTREAM/docker-compose.localhost.yml"
[[ ! -e "$SAFE_COMPOSE" ]] || { echo "Local Compose override already exists" >&2; exit 1; }
sed -E 's/^([[:space:]]*- )"([0-9]+(-[0-9]+)?):/\1"127.0.0.1:\2:/' docker-compose.yml > "$SAFE_COMPOSE"
if grep -E '^[[:space:]]*- "[0-9]+(-[0-9]+)?:' "$SAFE_COMPOSE"; then
  echo "Unsafe published port detected" >&2; exit 1
fi
docker compose -f "$SAFE_COMPOSE" up -d
echo "LOCAL four-validator developer cluster starting."
echo "Comet RPC: http://127.0.0.1:26657"
echo "EVM RPC: http://127.0.0.1:8545"
echo "Do not copy these keys into a public network."
