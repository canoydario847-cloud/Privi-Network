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
# --- One-time TEST gas grant to the Privi Anchor service wallet (valueless devnet coins) ---
# Set ANCHOR_FUND_BECH32 (bech32 form of the Anchor wallet). Runs in the background after the
# node is up, sends once from the local validator's test keyring, and records a marker so it
# never repeats. Failures are logged and never stop the node.
fund_anchor() {
  to="$1"; amount="${ANCHOR_FUND_AMOUNT:-1000000000000000000000}"   # default 1000 TEST
  case "$amount" in *[!0-9]*|"") echo "anchor-fund: invalid amount" >&2; return 1;; esac
  case "$to" in *[!a-z0-9]*|"") echo "anchor-fund: invalid address" >&2; return 1;; esac
  marker="/data/.anchor-funded-$to"
  [ -e "$marker" ] && { echo "anchor-fund: already funded $to"; return 0; }
  n=0
  until evmd status >/dev/null 2>&1; do
    n=$((n + 1)); [ "$n" -gt 120 ] && { echo "anchor-fund: node not ready" >&2; return 1; }
    sleep 5
  done
  sleep 15
  from=$(evmd keys list --keyring-backend test --home "$NODE_HOME" --output json | jq -r '.[0].name')
  from_addr=$(evmd keys show "$from" -a --keyring-backend test --home "$NODE_HOME")
  [ "${from_addr%%1*}" = "${to%%1*}" ] || { echo "anchor-fund: prefix mismatch ${from_addr%%1*} vs ${to%%1*}" >&2; return 1; }
  out=$(evmd tx bank send "$from" "$to" "${amount}atest" --keyring-backend test --home "$NODE_HOME" \
    --chain-id "$CHAIN_ID" --gas 300000 --fees 1000000000000000atest -y --output json 2>&1) || true
  code=$(printf '%s' "$out" | jq -r '.code // empty' 2>/dev/null)
  if [ "$code" = "0" ]; then
    touch "$marker"; echo "anchor-fund: sent ${amount}atest to $to tx=$(printf '%s' "$out" | jq -r .txhash)"
  else
    echo "anchor-fund: send failed: $out" >&2
  fi
}
if [ -n "${ANCHOR_FUND_BECH32:-}" ]; then
  ( fund_anchor "$ANCHOR_FUND_BECH32" ) &
fi
echo "Privi EVM single-validator DEVNET: Cosmos local-4221, EVM 262144. Only TEST coins."
exec evmd --home "$NODE_HOME" start --log_format plain \
  --minimum-gas-prices 0.0001atest \
  --json-rpc.enable true --json-rpc.address "0.0.0.0:$PORT" \
  --json-rpc.api "eth,net,web3" --chain-id "$CHAIN_ID"
