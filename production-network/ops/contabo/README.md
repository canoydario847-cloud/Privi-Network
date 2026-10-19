# Contabo staging preparation — PRVI mainnet is NOT LIVE

This is a no-secrets, no-spend deployment-preparation kit for **Privi World Corp's four proposed owner-controlled hosts**, all controlled by the **same** operator. Four servers do **not** mean four independent validator operators. No PRVI financial token, genesis, staking keys or validators are deployed by this directory. BNB PRIV and valueless TEST remain separate.

## New Cloud VPS 8 staging target — October 19, 2026

The owner has ordered and received a Contabo **Cloud VPS 8 (2026)** activation
email, separate from the earlier VPS 6. Treat the **new VPS 8** as the
designated first **valueless** Privi staging node. The new address is held in
the owner's private provider records and **must not be added to this
public repository** or confused with the earlier VPS 6 address.

A TCP connection attempt to the new VPS 8's standard SSH port 22 received
**connection refused** (as of October 19, 2026). The correct provider panel
assignment, OS image, actual running instance, host-key fingerprint, SSH
socket listener and firewall must be confirmed before access or any deployment.
**Do not try an emailed initial password against an unverified endpoint.**
See [trusted-console recovery](SSH_FIRST_LOGIN_RECOVERY.md).

After the new host becomes accessible, validate its 8-vCPU plan using the
**read-only** host probe, from a reviewed source checkout on the host:

```sh
PRIVI_EXPECTED_VCPU=8 bash production-network/ops/contabo/host_probe.sh
```

This setting checks a minimum of eight available vCPUs (no server upgrade or
billing operation). The default remains six for the older VPS 6. Actual
OS, RAM, storage, network firewall and host status checks still apply.
A single eight-core VPS **cannot stand in for four physically separate
signing hosts or a financial mainnet**. Do not enable RPC on public interfaces
or upload wallet/validator signing secrets during this stage.

## Order and provision (manual; no Contabo account access via repo)

1. The owner reports an order for **Contabo Cloud VPS 6 (2026), US Central, Auto Backup**, not the previously proposed VPS 8. The checkout confirmation indicates a **$15.00 initial one-month amount**, but an order confirmation is not a payment receipt or activation evidence. Do not purchase a duplicate server; check the Contabo VPS Control panel for assigned IPv4, instance details, actual 200 GB SSD vs 100 GB NVMe, OS image and active service. Read [one-server onboarding](ORDERED_VPS6_NEXT_STEPS.md). The Cloud VPS 6 is advertised as 6 shared vCPU and 12 GB RAM. Four physically separated validator hosts remain unprovisioned.
2. Create a new **ed25519 administrator SSH public key** locally if you do not already have one. Supply only the .pub file to the provider. Never commit private keys, API tokens, wallets, Comet signing keys or genesis keys.
3. For customized cloud-init, on **your own computer** create or use an ed25519 SSH public key (for example `ssh-keygen -t ed25519 -f ~/.ssh/privi_contabo_staging`). Keep the private key securely on your device. To generate a single valueless-staging cloud-init file with the **.pub** file, run `python3 production-network/ops/contabo/render_cloud_init.py --ssh-public-key-file ~/.ssh/privi_contabo_staging.pub --output-dir ./local-cloud-init --count 1`. The renderer rejects malformed/private keys and does not connect to Contabo; review `privi-stage-01.cloud-init.yaml` before submitting it through a provider-supported cloud-init field. Check cloud-init support on the specific VPS image; **do not** paste this YAML into an unrelated checkout field. Use `--count 4` only when you actually need four separate reviewed staging host configs; it gives distinct hostnames but does not generate consensus keys.
4. Verify SSH login and monitoring, enable network filtering after verifying the administrator access path, and establish an authenticated private overlay (such as WireGuard) before cross-host P2P. Never publish RPC, REST, gRPC, metrics or signer access. A sentry tier or screened-peer design is still needed for production.
5. Create four independent VMs only for a **valueless multi-host test**. A different VM/region label alone is not evidence of separate hypervisors, power or network failure domains. Production signing requires unique protected keys and rehearsed double-sign-safe recovery.
6. Fill candidate.json with nonsecret real instance IDs, addresses, regions, claimed failure domains, distinct overlay IPv4 addresses and SSH **public-key fingerprints**. Never add credentials or data that authorizes spending.


## Read-only VPS readiness diagnostic

After the first Ubuntu 24.04 LTS VPS is provisioned, review `host_probe.sh` and copy it to the host through your own authenticated SSH session. Run `bash host_probe.sh` on that machine (do not run it as an installer). It checks basic Ubuntu version, x86_64 architecture, minimum 10 GiB reported RAM and 60 GiB free disk (valueless VPS 6 staging floor), NTP synchronization, whether common RPC/metrics TCP ports listen outside loopback, and the presence of an active UFW host firewall. It makes **no network requests** and performs **no privileged modifications**. A PASS is not evidence of hypervisor independence, edge-firewall configuration, signed release, or validator readiness. Investigate every warning and failure manually.

**Bootstrapping sudo policy:** The cloud-init template provides SSH-key-only login and temporary passwordless sudo. On the first verified SSH session, confirm out-of-band recovery and configure a secure sudo credential/privilege reduction before exposing the host to untrusted traffic. Do not change SSH or UFW in a way that could lock out the only administrative access.

Run the following locally before using a candidate setup:

```sh
python3 -m unittest discover -s production-network/ops/contabo -p 'test_*.py' -v
bash -n production-network/ops/contabo/host_probe.sh
```

## Offline checks

From the repo root run:

- python3 production-network/ops/contabo/host_plan.py production-network/ops/contabo/candidate.json --mode draft
- python3 -m unittest discover -s production-network/ops/contabo -p 'test_*.py' -v
- python3 production-network/ops/contabo/host_plan.py production-network/ops/contabo/candidate.json --mode preflight

Expected: draft is structurally valid but reports missing evidence; tests pass; **preflight always exits 3 / NO-GO**. A self-filled manifest cannot independently verify a paid account, installed hardware, signed genesis, hardened host or validator key integrity. All independent testing, signed artifacts, security review and real financial-mainnet authorization remain blocked in ../MAINNET_LAUNCH_GATE.md.

## Spend boundary

This repository does not sign up for Contabo, place orders, create invoices or make billable API calls. The account holder must personally confirm checkout and provide host details via an approved nonsecret channel.
