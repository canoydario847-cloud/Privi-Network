# Contabo staging preparation — PRVI mainnet is NOT LIVE

This is a no-secrets, no-spend deployment-preparation kit for **Privi World Corp's four proposed owner-controlled hosts**, all controlled by the **same** operator. Four servers do **not** mean four independent validator operators. No PRVI financial token, genesis, staking keys or validators are deployed by this directory. BNB PRIV and valueless TEST remain separate.

## Order and provision (manual; no Contabo account access via repo)

1. Open https://contabo.com/en-us/vps/ and review the **actual checkout price and commitment**. For early testing, start with **one** Ubuntu 24.04 LTS instance. The vendor advertises Cloud VPS 8 with 8 vCPU, 24 GB RAM, 300 GB SSD, but price/size/region availability must be checked before paying.
2. Create a new **ed25519 administrator SSH public key** locally if you do not already have one. Supply only the .pub file to the provider. Never commit private keys, API tokens, wallets, Comet signing keys or genesis keys.
3. For customized cloud-init, replace REPLACE_WITH_REAL_SSH_ED25519_PUBLIC_KEY in cloud-init.template.yaml with your own SSH public key, and review it before submission. This template does **not** start a network. Cloud-init availability and image behavior vary; verify login before enforcing firewalls.
4. Verify SSH login and monitoring, enable network filtering after verifying the administrator access path, and establish an authenticated private overlay (such as WireGuard) before cross-host P2P. Never publish RPC, REST, gRPC, metrics or signer access. A sentry tier or screened-peer design is still needed for production.
5. Create four independent VMs only for a **valueless multi-host test**. A different VM/region label alone is not evidence of separate hypervisors, power or network failure domains. Production signing requires unique protected keys and rehearsed double-sign-safe recovery.
6. Fill candidate.json with nonsecret real instance IDs, addresses, regions, claimed failure domains, distinct overlay IPv4 addresses and SSH **public-key fingerprints**. Never add credentials or data that authorizes spending.

## Offline checks

From the repo root run:

- python3 production-network/ops/contabo/host_plan.py production-network/ops/contabo/candidate.json --mode draft
- python3 -m unittest discover -s production-network/ops/contabo -p 'test_*.py' -v
- python3 production-network/ops/contabo/host_plan.py production-network/ops/contabo/candidate.json --mode preflight

Expected: draft is structurally valid but reports missing evidence; tests pass; **preflight always exits 3 / NO-GO**. A self-filled manifest cannot independently verify a paid account, installed hardware, signed genesis, hardened host or validator key integrity. All independent testing, signed artifacts, security review and real financial-mainnet authorization remain blocked in ../MAINNET_LAUNCH_GATE.md.

## Spend boundary

This repository does not sign up for Contabo, place orders, create invoices or make billable API calls. The account holder must personally confirm checkout and provide host details via an approved nonsecret channel.
