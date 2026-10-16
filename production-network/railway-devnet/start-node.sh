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
  if [ -n "$(ls -A /data)" ]; then
    echo "Existing /data without expected genesis: refusing to replace persistent chain" >&2
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
