#!/usr/bin/env bash
# Privi self-operated seven-node staging cluster. ONE owner, seven disposable keys.
# Not native PRVI financial mainnet. Never modify existing Railway devnet.
set -euo pipefail
umask 077
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
UPSTREAM="$ROOT/.upstream-seven-evm"
STATE="$ROOT/.seven-validator-state"
TAG="v0.7.3"
SHA="c3ae9067a7eadcdea55a5192226916deb44c71c4"
CHAIN="local-privi-seven-4221"
IMAGE="cosmos/evmd:privi-seven-v073"
COMPOSE="$UPSTREAM/docker-compose.privi-seven.yml"

for cmd in git docker make python3; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing required command: $cmd" >&2; exit 1; }
done
docker info >/dev/null 2>&1 || { echo "Docker daemon is unavailable." >&2; exit 1; }
# Never overwrite any user's validator state, even partial initialization.
[[ ! -e "$STATE" && ! -L "$STATE" ]] || {
  echo "Seven-validator state already exists: $STATE. Refusing to overwrite it." >&2
  exit 1
}
[[ ! -e "$UPSTREAM" && ! -L "$UPSTREAM" ]] || {
  echo "Dedicated seven-validator checkout already exists: $UPSTREAM. Refusing to overwrite." >&2
  exit 1
}
git clone --depth 1 --branch "$TAG" https://github.com/cosmos/evm.git "$UPSTREAM"
[[ "$(git -C "$UPSTREAM" rev-parse HEAD)" == "$SHA" ]] || {
  echo "Pinned upstream Cosmos EVM SHA mismatch; refusing to build." >&2; exit 1
}
GO_VERSION="1.25.9"
DOCKERFILE="$UPSTREAM/contrib/images/evmd-env/Dockerfile"
for module in go.mod evmd/go.mod; do
  grep -Fxq "go $GO_VERSION" "$UPSTREAM/$module" || {
    echo "Unexpected Go version for $module" >&2; exit 1
  }
done
sed -i "s|^FROM golang:1[.]24-alpine AS evmd-builder$|FROM golang:$GO_VERSION-alpine AS evmd-builder|" "$DOCKERFILE"
grep -Fxq "FROM golang:$GO_VERSION-alpine AS evmd-builder" "$DOCKERFILE" || {
  echo "Unexpected Docker builder image version" >&2; exit 1
}
(cd "$UPSTREAM" && make localnet-build-env)
docker image inspect cosmos/evmd >/dev/null 2>&1
docker tag cosmos/evmd "$IMAGE"

mkdir -m 700 "$STATE"
# Make the first-time state accessible exclusively to NONROOT uid in the upstream image.
docker run --rm --user 0:0 --entrypoint /bin/sh \
    -v "$STATE:/data" "$IMAGE" -ec '
  chown 1025:1025 /data
  chmod 0700 /data
  mkdir -m 0700 /data/staging
  chown 1025:1025 /data/staging
'
# Upstream init creates seven distinct disposable validators with one shared genesis.
# Suppress output from init-files to prevent printing development mnemonic material.
# Bypass upstream wrapper: it implicitly selects /data/node0/evmd as its
# --home and initializes an unrelated node0 directory BEFORE init-files,
# causing a collision with the isolated seven-node state layout.
# Use an ephemeral, container-only CLI home outside the shared /data mount.
docker run --rm --entrypoint /evmd/evmd \
    -v "$STATE:/data" "$IMAGE" \
    --home /tmp/privi-seven-init-cli testnet init-files --validator-count 7 --chain-id "$CHAIN" \
    --starting-ip-address 192.168.77.10 --keyring-backend=test \
    --use-docker=true -o /data/staging >/dev/null 2>&1 || {
  echo "Seven-validator initialization failed; state preserved for investigation." >&2
  exit 1
}
# Split initial common /data tree into separate, private bind mounts.
# Only operator root performs this move; no process sees peers' signing keys.
docker run --rm --user 0:0 --entrypoint /bin/sh \
    -v "$STATE:/data" "$IMAGE" -ec '
  for n in 0 1 2 3 4 5 6; do
    home="/data/staging/node${n}/evmd"
    [ -s "${home}/config/genesis.json" ] || exit 1
    [ -s "${home}/config/priv_validator_key.json" ] || exit 1
    [ -s "${home}/config/config.toml" ] || exit 1
  done
  # Fail closed if upstream created ANY node directory outside staging.
  for n in 0 1 2 3 4 5 6; do
    [ ! -e "/data/node${n}" ] || { echo "Unexpected preexisting node root" >&2; exit 1; }
  done
  for n in 0 1 2 3 4 5 6; do
    mkdir -m 0700 "/data/node${n}"
    mv "/data/staging/node${n}/evmd" "/data/node${n}/evmd"
    rmdir "/data/staging/node${n}"
    cfg="/data/node${n}/evmd/config/config.toml"
    sed -i "/^\[mempool\]/,/^\[/ s/^[[:space:]]*type[[:space:]]*=[[:space:]]*\"flood\"/type = \"app\"/" "$cfg"
    sed -n "/^\[mempool\]/,/^\[/p" "$cfg" | grep -Eq "^[[:space:]]*type[[:space:]]*=[[:space:]]*\"app\"" || exit 1
    chmod 0700 "/data/node${n}" "/data/node${n}/evmd" "/data/node${n}/evmd/config"
    chmod 0600 "/data/node${n}/evmd/config/priv_validator_key.json"
    chmod 0600 "/data/node${n}/evmd/config/node_key.json"
  done
  # Upstream init-files leaves unsigned development gentxs in a shared
  # staging/gentxs directory. Keep it PRIVATE and unchanged for audit.
  [ -d /data/staging/gentxs ] || { echo "Missing upstream gentx archive" >&2; exit 1; }
  [ -z "$(find /data/staging -mindepth 1 -maxdepth 1 ! -name gentxs -print -quit)" ] || {
    echo "Unrecognized residual staging state" >&2; exit 1;
  }
  chmod 0700 /data/staging /data/staging/gentxs
  chown -R 1025:1025 /data
'
python3 "$HERE/generate_compose.py" --output "$COMPOSE"
docker compose -f "$COMPOSE" config --quiet
docker compose -f "$COMPOSE" up -d
echo "SEVEN self-controlled valueless Cosmos EVM validator nodes have been started."
echo "Cosmos chain: $CHAIN; Ethereum demo chain: 262144."
echo "Seven loopback Comet RPC endpoints: 127.0.0.1:26657 through 26717, step 10."
echo "EVM JSON-RPC: http://127.0.0.1:8545."
echo "Run bash production-network/seven-validator/verify-seven.sh to test actual consensus."
echo "DO NOT call this independent financial Privi mainnet or represent TEST as PRVI."
