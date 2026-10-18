#!/usr/bin/env bash
# Fetch pinned dependencies into lib/ (not committed).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p lib
[ -d lib/openzeppelin-contracts ] || git clone -q --depth 1 --branch v5.1.0 https://github.com/OpenZeppelin/openzeppelin-contracts lib/openzeppelin-contracts
[ -d lib/forge-std ] || git clone -q --depth 1 --branch v1.10.0 https://github.com/foundry-rs/forge-std lib/forge-std
echo "Dependencies ready."
