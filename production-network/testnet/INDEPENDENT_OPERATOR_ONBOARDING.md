# Privi Public TESTnet — Independent Validator Operator Onboarding

**STATUS: OPERATOR RECRUITMENT / NOT DEPLOYED.**
There are **zero** independently verified public Privi validators recorded in
the current launch evidence. A passing GitHub Actions four-validator job runs
four *ephemeral, same-runner* dev containers and is **not** an independent
public testnet. These steps do not activate or create financial PRVI.

## Coordinator-owned preparation (never share private keys)

1. Recruit at least **four unaffiliated operational controllers** willing to
   own and run their validator nodes, including independent accounts and
   signer custody. Four VMs paid for by one person remain a **single
   operational controller**, even if they are in separate regions.
2. Identify each operator using a trusted off-repository channel. Obtain
   organization/contact, operating jurisdiction, responsibility agreement,
   key-management practices, response contact, fault domain and hosting
   provider. **Do not put personal contact data or credentials in this public
   repository.** Independently confirm that operators do not share privileged
   cloud control, private keys, signing hosts or a single on-call dependency.
3. Agree on distinct, reviewed **public-testnet-only** Cosmos and EIP-155
   chain identifiers. Both must be separate from the local developer IDs
   `local-4221` (Cosmos) and `262144` (EVM) and from the future PRVI financial
   mainnet. Choose the valueless native TEST denomination, economics and
   genesis parameters after review; do **not** use PRVI or bridge BNB PRIV.
4. Freeze a reproducible public-testnet binary digest. Upstream reference
   `evmd` v0.7.3 is a starting point, NOT an audited custom PRVI network.
   Do not copy the disposable `.testnets` developer private keys.
5. Distribute the proposed TESTnet genesis securely to each operator for
   independent review. Operators inspect chain IDs, supply, fee/staking
   denominators, validator pubkeys, staking state and any privileged module
   authorities, and agree on the **exact genesis SHA-256**.

## Each validator operator — acceptance checklist

- [ ] I independently control my cloud/on-premises account and OS/admin role.
- [ ] I generated my **own** validator consensus and P2P secrets on my host or
      protected remote signer; coordinator never received the private keys.
- [ ] I have separate production-grade secret storage, backup/restore policy,
      slashing/double-sign prevention, monitoring, recovery and contact.
- [ ] I have independently reviewed the frozen binary SHA-256, unsigned TEST
      genesis, chain IDs and token denomination; **only public data** leaves
      my workstation.
- [ ] My CometBFT **consensus address** (40 hexadecimal characters, no `0x`)
      and my off-chain attestation public key are present in the coordinator's
      review manifest. My signing key is **not** a validator consensus key.
- [ ] I have independently confirmed P2P peer details with other operators
      and checked firewall/sentry topology; validator RPC/admin/remote-signer
      ports are not exposed to the public internet.
- [ ] I have reviewed/tested host patching, backups, restore timing, alert
      delivery and no-double-sign safety.
- [ ] I have signed the exact off-chain attestation payload, below, with a
      **separate** Ed25519 attestation key I control.
- [ ] My organization/control, infrastructure diversity, consensus key
      ownership and document identity are independently reviewed by a
      human verifier (Ed25519 proof-of-possession alone does **not** prove these).

## Off-chain genesis identity signature — operator workstation only

The cryptographic script uses **Node.js built-in crypto**, no package installs.
An off-chain key signs **only a reviewed testnet claim**; it must not be the
live validator consensus key, treasury key, exchange key or real wallet key.

On **each operator's private workstation** (not on GitHub or ChatGPT):

```bash
umask 077
openssl genpkey -algorithm ED25519 -out operator-attestation-private.pem
openssl pkey -in operator-attestation-private.pem -pubout -out operator-attestation-public.pem
```

The private PEM remains solely under operator control. In a protected copy
of the coordinator manifest, fill in **only** your operator's following
fields after inspecting the common `cosmos_chain_id`, `evm_chain_id`,
`genesis_sha256` and `binary_sha256`:

```json
{
  "operator_id": "your-org-testnet-operator",
  "consensus_address": "40_HEX_DIGITS_FROM_YOUR_NODE",
  "fault_domain": "your-independent-site-identifier",
  "operator_controls_keys": true,
  "independence_attestation_url": "https://your-public-reviews.example.org/attestation",
  "attested_utc": "2026-10-17T23:00:00Z",
  "attestation_public_key_pem": "-----BEGIN PUBLIC KEY-----\nYOUR_ACTUAL_ED25519_PUBLIC_KEY\n-----END PUBLIC KEY-----\n",
  "attestation_signature_base64": ""
}
```

The values above are **placeholders**, not a registered operator or a real
signature. The URL must point to genuine public non-secret evidence after
your identity and control review. Time must reflect when *you* actually
attested; do not copy the example time.

Generate the exact canonical bytes in a trusted copy of the program:

```bash
node production-network/ops/verify_operator_attestations.cjs \
  /secure/review/public-testnet-manifest.json \
  --payload your-org-testnet-operator > /secure/review/operator-claim.bin

# Sign only after visually reviewing the manifest and payload.
openssl pkeyutl -sign -rawin \
  -inkey operator-attestation-private.pem \
  -in /secure/review/operator-claim.bin \
  -out /secure/review/operator-signature.bin

# Copy ONLY this result and your public PEM to the coordinator.
openssl base64 -A -in /secure/review/operator-signature.bin
```

The operator enters the resulting Base64 text into their public
`attestation_signature_base64` field. Do not disclose the private PEM,
contents of other keys, CLI history containing passwords, validator state,
mnemonics, or secret remote-signer data.

The signature binds the operator ID, **consensus address**, self-declared
fault domain, evidence URL, UTC attestation timestamp, testnet chain IDs,
frozen candidate genesis hash, and frozen binary hash. Any change to
any field requires re-signing.

## Coordinator verification (offline, before deployment)

Run the attestation verifier against the real operator-reviewed manifest:

```bash
node production-network/ops/verify_operator_attestations.cjs \
  /secure/review/public-testnet-manifest.json
```

The verifier requires four distinct operator IDs, consensus addresses,
fault domains and off-chain Ed25519 public keys and validates every detached
signature. It **does not** establish that the operators are unaffiliated,
that these are *their actual deployed* consensus addresses, or that the
validator signing keys are in independent custody.

Also run the separate genesis and node-state checker from
[PUBLIC_TESTNET.md](../ops/PUBLIC_TESTNET.md). Its `--check-live` mode reads
the network after the independently controlled nodes and endpoints actually
exist. Both checks and an independent human operator review must pass.

## Network deployment boundary and fault drills

Operators deploy **only their own valueless TESTnet** nodes. The project
coordinator can distribute reviewed public peer IDs and genesis hashes but
should never centralize validator private keys or create "independent"
operators by running all four hosts under a shared account.

Require successful node restarts; one-validator downtime; state sync / safe
restore; monitoring and paging; upgrade rollback; signed transfer receipts;
RPC abuse-limit checks; explorer accuracy; and conflicting-signature
prevention before calling the public TESTnet accepted.

Separate final independent audit, PRVI hard-cap proof, signed production
genesis and formal go/no-go still block all financial PRVI launch claims.
