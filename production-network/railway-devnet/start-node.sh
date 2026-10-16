#!/bin/sh
# Valueless ONE-validator EVM devnet. Never move real PRIV to this network.
set -eu
umask 077
CHAIN_ID="local-4221"
NODE_HOME="/data/node0/evmd"
PORT="$PORT"
case "$PORT" in *[!0-9]*|"") echo "Invalid PORT" >&2; exit 1;; esac
if [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
  echo "PORT must be 1024-65535" >&2; exit 1
fi
if [ ! -f "$NODE_HOME/config/genesis.json" ]; then
  # A freshly formatted ext4 Railway volume may contain an empty lost+found
  # directory. That is filesystem metadata, NOT previous chain state.
  # Refuse to overwrite any other files, including partially initialized nodes.
  if [ -e /data/lost+found ]; then
    if [ ! -d /data/lost+found ] || [ -n "$(ls -A /data/lost+found)" ]; then
      echo "Volume lost+found is not an empty directory; refusing initialization" >&2
      exit 1
    fi
  fi
  if [ -n "$(find /data -mindepth 1 -maxdepth 1 ! -name lost+found -print -quit)" ]; then
    echo "Unrecognized persistent /data contents; refusing to overwrite chain" >&2
    find /data -mindepth 1 -maxdepth 1 -print >&2
    exit 1
  fi
  echo "Initializing SINGLE new valueless developer validator"
  evmd testnet init-files --validator-count 1 --chain-id="$CHAIN_ID" \
    --keyring-backend=test --starting-ip-address 192.168.10.2 \
    --use-docker=true -o /data
fi
CONF="$NODE_HOME/config/config.toml"
GENESIS="$NODE_HOME/config/genesis.json"
[ -s "$CONF" ] && [ -s "$GENESIS" ] || {
  echo "Incomplete persistent state; refusing startup" >&2
  exit 1
}
jq -e --arg chain "$CHAIN_ID" '.chain_id == $chain' "$GENESIS" >/dev/null || {
  echo "Unexpected chain ID in persistent genesis" >&2; exit 1
}
# Cosmos EVM application mempool requires CometBFT mempool.type=app.
sed -i '/^\[mempool\]/,/^\[/ s/^[[:space:]]*type[[:space:]]*=[[:space:]]*"flood"/type = "app"/' "$CONF"
sed -n '/^\[mempool\]/,/^\[/p' "$CONF" | grep -Eq '^[[:space:]]*type[[:space:]]*=[[:space:]]*"app"' || {
  echo "Invalid EVM mempool config" >&2; exit 1
}
echo "Privi EVM single-validator DEVNET: Cosmos local-4221, EVM 262144. Only TEST coins."
exec evmd --home "$NODE_HOME" start --log_format plain \
  --minimum-gas-prices 0.0001atest \
  --json-rpc.enable true --json-rpc.address "0.0.0.0:$PORT" \
  --json-rpc.api "eth,net,web3" --chain-id "$CHAIN_ID"
