# Contabo first-boot SSH recovery (nonfinancial Privi staging)

**Scope:** One newly activated owner-controlled Contabo Cloud VPS 6. This document is a manual runbook only. It does not contact Contabo, run remote commands, turn on consensus, create keys or activate the PRVI financial mainnet.

The owner has separately confirmed an IPv4 address that agrees with Contabo's "Your login data!" message. **Do not commit the address, initial password, credentials, VNC details, API credentials, or a private key into GitHub.** An external basic TCP attempt to port 22 received "connection refused"; that observation alone does not prove that the service is fully unavailable, or that the OS is Ubuntu.

## First: use the provider to verify the VPS

1. Sign in directly at https://new.contabo.com/.
2. Go to **Servers & Hosting > VPS/VDS**. Confirm the correct server shows running, has the expected assigned IPv4, and that its current OS image is Linux.
3. If SSH access is refused, use the service's **More > VNC Control** option. Per Contabo's help desk, VNC may require enabling the feature and rebooting the VPS. A third-party VNC *viewer* is required; a VNC viewer does not run inside the Contabo web panel.
4. Log in using the credentials held privately by the owner. Do not disclose them to anyone assisting with the setup. Disable VNC when finished.

Contabo reference: https://help.contabo.com/en/support/solutions/articles/103000407800-how-to-connect-to-your-server-using-vnc

## From the provider-connected Linux console (read-only)

These commands inspect OS and networking; they do not install software:

```sh
cat /etc/os-release
uname -m
systemctl is-active ssh || systemctl is-active sshd || true
sudo ss -lntp | grep -E '(:22[[:space:]]|:22$)' || true
sudo ufw status verbose || true
```

If Ubuntu 24.04 is confirmed and `ssh` is missing or inactive, use Ubuntu's documented OpenSSH packages/service setup, after verifying administrator/recovery access:

```sh
sudo apt-get update
sudo apt-get install openssh-server
sudo systemctl enable --now ssh
sudo systemctl status ssh --no-pager
```

Only run these commands in the **owner-controlled trusted console**; do not provide the initial password to any helper. If the service runs but remote port 22 remains unavailable, review provider firewall and host firewall policy. Never disable the entire firewall as a diagnostic shortcut, and avoid changing SSH listening port without documenting it and confirming console recovery.

## If SSH is active locally but TCP/22 is refused remotely

Run the new **read-only** diagnostic directly inside the authenticated VPS/VNC console:

```sh
sudo bash production-network/ops/contabo/ssh_readonly_diagnostics.sh
```

The script requires only `systemctl`, `ss`, `awk`, `ufw` (optional) and standard shell tools. It reports whether the SSH process or socket is active, whether port 22 binds only loopback or a non-loopback address, and whether UFW appears active. It does **not** change SSH configuration, firewall rules, credentials or cloud resources.

- **No listener on TCP/22:** inspect the SSH socket/service configuration and logs inside VNC. An active `ssh.service` is not sufficient without a TCP listener.
- **Loopback-only listener:** check `sshd_config`, `sshd_config.d` and `ssh.socket` listen configuration. Preserve a recovery path before changing binding.
- **Non-loopback listener, still refused from outside:** check Contabo network/provisioning status, provider firewall, host UFW/iptables/nftables rules and IPv4 assignment. A local listener check alone **does not prove external reachability**.
- **Public SSH working:** compare the host ED25519 fingerprint from VNC to the initial client prompt, then log in; do not bypass key checking.

Never disclose passwords, keys, API credentials or other private console data as diagnostic evidence. A concise report of `LOCAL ONLY`, `LISTENING`, `No TCP listener`, and UFW active/inactive is sufficient.

## Confirm the SSH host key before login

From the VNC-connected Linux console, compute the public host fingerprint:

```sh
sudo ssh-keygen -l -f /etc/ssh/ssh_host_ed25519_key.pub
```

From the owner's local device, initiate `ssh root@SERVER_PUBLIC_IPV4` and compare the displayed host fingerprint to the console value before trusting it. Never use `StrictHostKeyChecking=no`, copy private SSH keys to the server, or publish credentials. Contabo's help article explains this same fingerprint verification path:

https://help.contabo.com/en/support/solutions/articles/103000271398-how-do-i-set-up-an-ssh-connection-

## Once local SSH works

Verify `Ubuntu VERSION_ID`, memory, CPU, disk and security posture with the existing *read-only* `host_probe.sh` in this directory. Create a non-root SSH-key-only administrator, verify the new login in a second session, then restrict root/password logins while keeping recovery access. Back up existing configuration before security changes. Never run financial PRVI, production signing keys, or genesis on an untested single VPS.

Four owner-controlled hosts are **one centrally controlled operator**, not four independent organizations. The 1,000,000,000 PRVI financial mainnet remains **NO-GO** under `../MAINNET_LAUNCH_GATE.md`.
