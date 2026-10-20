# Privi / Contabo Cloud VPS 6 — one-server onboarding

**Status: awaiting Contabo VPS provisioning evidence. NO financial mainnet or real PRVI.**

This is specific to the owner-reported **Contabo Cloud VPS 6** subscription in **US Central** with **Auto Backup**. The product is advertised with 6 shared vCPU, 12 GB RAM, and either 200 GB SSD or 100 GB NVMe depending on selected storage. **The storage choice, installed operating system, provisioned public IP, hostname, invoice-paid state, and SSH access have not been independently verified.** Do not enter order numbers, customer IDs or credentials in this repository.

## 1. Verify the service exists (the account holder only)

- Open https://new.contabo.com/ directly, then `Servers & Hosting > VPS Control`. Find the **server row**, not only the order confirmation. Record its public IPv4 address, displayed default username, OS image and running state in your *private* records.
- Alternatively use `Network Services > IP Assignment` to find the included IP assigned to the VPS.
- Contabo normally sends a separate email titled **Your login data!** after provisioning. A customer-panel password/reset email is **not** the same as server activation.
- Verify payment in `Account > Billing & Payment`. A received *order confirmation* without active service does not establish that the VPS exists.
- For setup problems use Contabo support, not arbitrary remote operators or unsolicited password reset links.

## 2. First login without disclosing a password

Use the *actual* username shown in the Contabo VPS Control panel, your own private local SSH key or password, and the actual public IP:

```sh
ssh -o StrictHostKeyChecking=ask YOUR_DISPLAYED_USERNAME@YOUR_SERVER_IPV4
```

Verify the SSH host-key fingerprint using an independently trusted control-panel console, the server VNC/rescue console or other trusted out-of-band method **before accepting the fingerprint**. Never turn off SSH host-key checking. Do not paste passwords, private keys, wallet mnemonics, API tokens, or unredacted `~/.ssh` files in chat, tickets or GitHub.

If you did not select a cloud-init/SSH key *before* Contabo created the VM, simply uploading the generated YAML file to your local machine will **not** apply it retroactively. Use supported Contabo reinstall/customization controls only with an explicit backup and acknowledgement of data loss. For an already active password-provisioned VM, verify recovery console access and add your own SSH public key through the normal authorized administrator login, then separately disable password SSH after testing key login.

## 3. Safe read-only machine checks

After verifying authorized access, run:

```sh
uname -m
cat /etc/os-release | grep -E '^(ID|VERSION_ID)='
nproc
free -h
df -h /
sudo ss -lnt
```

Review the output: advertised VPS 6 sizing is **6 vCPU, 12 GB RAM**, subject to virtualization reporting; staging floor is **10 GiB reported RAM and 60 GiB free disk**. Smaller available memory/storage may be a configuration mismatch, disk consumption issue or storage-layout difference. This is a valueless developer staging floor, *not* a production blockchain capacity guarantee.

After reviewing `host_probe.sh`, copy it from a trusted checkout and run locally on the VPS:

```sh
bash production-network/ops/contabo/host_probe.sh
```

Do not run `curl URL | sh` from unknown sources. Do not run Docker consensus nodes, load production genesis or handle financial assets on an unverified host. The check performs no installation, no remote requests and no service changes.

## 4. Host isolation / next milestone

- First VPS is for initial **valueless TEST staging and diagnostics only**, never four validators or an entire financial mainnet on one machine.
- For a future **four-host** valueless consensus test, verify separate VM identities, failure domains, private overlays, firewalls and screened peers. Four VMs all run by Privi World Corp are still centrally controlled, not decentralized independent operators.
- The tests and proposed launch gates in `../MAINNET_LAUNCH_GATE.md` must remain enforced. BNB PRIV is separate; PRVI financial mainnet has **not** been started.

**Needed next:** the server's *public IP address* and OS image (plus the nonsecret default username, if available) when the VPS Control panel shows it running. Never request or share root/admin passwords or private keys.
