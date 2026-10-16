#!/usr/bin/env python3
"""Generate an isolated, loopback-only 7-validator Cosmos EVM STAGING compose file.

Pure stdlib generator; no keys, tokens, wallet addresses, server purchases,
deployments or daemon side effects. Seven validators controlled by one owner
are NOT independent operators. Do not use this as a financial PRVI mainnet.
"""
import argparse
import ipaddress
from pathlib import Path

VALIDATORS = 7
COSMOS_CHAIN_ID = "local-privi-seven-4221"
EVM_NUMERIC_ID = 262144  # Upstream cosmos/evm v0.7.3 reference EVM ID
SUBNET = "192.168.77.0/24"
FIRST_IP = "192.168.77.10"
P2P_PORT = 26656
COMET_RPC_PORT = 26657
ETH_RPC_PORT = 8545


def render():
    net=ipaddress.ip_network(SUBNET)
    first=ipaddress.ip_address(FIRST_IP)
    if first not in net or first + VALIDATORS - 1 not in net:
        raise ValueError("Validator addresses must belong to dedicated bridge subnet")
    lines=[
        "# GENERATED Privi self-operated SEVEN-VALIDATOR STAGING network.",
        "# All keys are disposable and controlled by ONE operator, not independent validators.",
        "# NOT PRVI mainnet, not a token launch; TEST is permanently valueless.",
        "name: privi-seven-validator-stage",
        "services:",
    ]
    for i in range(VALIDATORS):
        port=COMET_RPC_PORT+10*i
        ethport=ETH_RPC_PORT+10*i
        home=f"/data/node{i}/evmd"
        source=f"../.seven-validator-state/node{i}/evmd"
        lines.extend([
            f"  validator{i}:",
            "    image: cosmos/evmd:privi-seven-v073",
            f"    container_name: privi-seven-validator{i}",
            "    restart: unless-stopped",
            "    environment:",
            f"      ID: \"{i}\"",
            "      DEBUG: \"0\"",
            "      LOG: evmd.log",
            "    cap_drop:",
            "      - ALL",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    ports:",
            f"      - \"127.0.0.1:{port}:26657\"",
        ])
        if i==0:
            lines.append(f"      - \"127.0.0.1:{ethport}:8545\"")
        lines.extend([
            "    volumes:",
            f"      - \"{source}:{home}:rw\"",
            "    command:",
            "      - start",
            "      - --log_format",
            "      - plain",
            "      - --minimum-gas-prices",
            "      - 0.0001atest",
            "      - --json-rpc.enable",
            f"      - \"{'true' if i==0 else 'false'}\"",
            "      - --json-rpc.api",
            "      - eth,net,web3",
            "      - --chain-id",
            f"      - {COSMOS_CHAIN_ID}",
            "    networks:",
            "      privi_seven:",
            f"        ipv4_address: {first+i}",
        ])
    lines.extend([
        "networks:",
        "  privi_seven:",
        "    driver: bridge",
        "    ipam:",
        "      config:",
        f"        - subnet: {SUBNET}",
        "",
    ])
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--stdout",action="store_true")
    args=p.parse_args()
    rendered=render()
    if args.stdout:
        print(rendered,end="")
        return
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit("Refusing to overwrite an existing seven-validator compose file")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf-8") as f:
        f.write(rendered)
    print(f"Created isolated, loopback-only {VALIDATORS}-validator developer compose at {args.output}")
    print("DO NOT pass this network off as independent PRVI mainnet; it uses valueless upstream TEST.")

if __name__=="__main__":
    main()
