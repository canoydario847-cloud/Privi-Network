#!/bin/bash
# Privi Devnet node. Initializes a single-validator chain on first boot (state lives on the
# persistent disk), then runs evmd with JSON-RPC on localhost and the public gateway on $PORT.
set -euo pipefail

HOME_DIR="${DEVNET_HOME:-/data/evmd}"
CHAIN="${DEVNET_COSMOS_CHAIN_ID:-privi-devnet-1}"
EVMID="${DEVNET_EVM_CHAIN_ID:-772626}"
DENOM=atest
KR=test   # keys live only on this disk; TEST has no value
GENESIS="$HOME_DIR/config/genesis.json"
CONFIG_TOML="$HOME_DIR/config/config.toml"
APP_TOML="$HOME_DIR/config/app.toml"

jqi() { jq "$1" "$GENESIS" > "$GENESIS.tmp" && mv "$GENESIS.tmp" "$GENESIS"; }

if [ ! -f "$GENESIS" ]; then
  echo "[devnet] first boot: initializing $CHAIN (EVM chain id $EVMID) in $HOME_DIR"
  mkdir -p "$HOME_DIR"
  evmd config set client chain-id "$CHAIN" --home "$HOME_DIR"
  evmd config set client keyring-backend "$KR" --home "$HOME_DIR"
  evmd keys add validator --keyring-backend "$KR" --algo eth_secp256k1 --home "$HOME_DIR" > "$HOME_DIR/validator-key.txt" 2>&1
  chmod 600 "$HOME_DIR/validator-key.txt"
  evmd init privi-devnet-validator --chain-id "$CHAIN" --home "$HOME_DIR" > /dev/null 2>&1

  # Same genesis shape as upstream local_node.sh (v0.7.3), with Privi's chain ids.
  jqi '.app_state.staking.params.bond_denom="atest"'
  jqi '.app_state.gov.deposit_params.min_deposit[0].denom="atest"'
  jqi '.app_state.gov.params.min_deposit[0].denom="atest"'
  jqi '.app_state.gov.params.expedited_min_deposit[0].denom="atest"'
  jqi '.app_state.evm.params.evm_denom="atest"'
  jqi '.app_state.mint.params.mint_denom="atest"'
  jqi '.app_state.bank.denom_metadata=[{"description":"Valueless gas token for the Privi Devnet.","denom_units":[{"denom":"atest","exponent":0,"aliases":["attotest"]},{"denom":"test","exponent":18,"aliases":[]}],"base":"atest","display":"test","name":"Privi Devnet Test","symbol":"TEST","uri":"","uri_hash":""}]'
  jqi '.app_state.evm.params.active_static_precompiles=["0x0000000000000000000000000000000000000100","0x0000000000000000000000000000000000000400","0x0000000000000000000000000000000000000800","0x0000000000000000000000000000000000000801","0x0000000000000000000000000000000000000802","0x0000000000000000000000000000000000000803","0x0000000000000000000000000000000000000804","0x0000000000000000000000000000000000000805","0x0000000000000000000000000000000000000806","0x0000000000000000000000000000000000000807"]'
  jqi '.app_state.erc20.native_precompiles=["0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"]'
  jqi '.app_state.erc20.token_pairs=[{contract_owner:1,erc20_address:"0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",denom:"atest",enabled:true}]'
  jqi '.consensus.params.block.max_gas="30000000"'

  # Validator stake, plus TEST for every wallet Privi services sign with (anchor wallet, owner).
  evmd genesis add-genesis-account validator 100000000000000000000000000$DENOM --keyring-backend "$KR" --home "$HOME_DIR"
  IFS=',' read -ra FUND <<< "${DEVNET_FUND_ADDRESSES:-}"
  for a in "${FUND[@]}"; do
    a="$(echo "$a" | tr -d '[:space:]')"; [ -z "$a" ] && continue
    bech="$(python3 /app/bech32.py "$a")"
    echo "[devnet] funding $a ($bech) with 1,000,000 TEST"
    evmd genesis add-genesis-account "$bech" 1000000000000000000000000$DENOM --home "$HOME_DIR"
  done

  evmd genesis gentx validator 1000000000000000000000$DENOM --gas-prices 0$DENOM \
    --keyring-backend "$KR" --chain-id "$CHAIN" --home "$HOME_DIR" > /dev/null 2>&1
  evmd genesis collect-gentxs --home "$HOME_DIR" > /dev/null 2>&1
  evmd genesis validate-genesis --home "$HOME_DIR"

  # One block every ~2s while busy; an empty block at most every 30s when idle (saves disk).
  sed -i 's/timeout_commit = "5s"/timeout_commit = "2s"/' "$CONFIG_TOML"
  sed -i 's/create_empty_blocks_interval = "0s"/create_empty_blocks_interval = "30s"/' "$CONFIG_TOML"
  sed -i 's/type = "flood"/type = "app"/' "$CONFIG_TOML"
  # Turn on JSON-RPC (bound to localhost; only the gateway is public).
  sed -i 's/enable = false/enable = true/g' "$APP_TOML"
  echo "[devnet] genesis ready"
fi

evmd start \
  --home "$HOME_DIR" \
  --chain-id "$CHAIN" \
  --evm.evm-chain-id "$EVMID" \
  --pruning custom --pruning-keep-recent 100000 --pruning-interval 100 \
  --minimum-gas-prices "0$DENOM" \
  --evm.min-tip 0 \
  --json-rpc.enable \
  --json-rpc.address 127.0.0.1:8545 \
  --json-rpc.ws-address 127.0.0.1:8546 \
  --json-rpc.api eth,net,web3,txpool \
  --log_level "${DEVNET_LOG_LEVEL:-warn}" &
NODE_PID=$!
trap 'kill $NODE_PID 2>/dev/null' TERM INT

exec python3 /app/gateway.py
