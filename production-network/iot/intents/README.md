# Privi Intent Capsules — beyond one-contract-per-workflow (research preview)

Privi Intent Capsules are **signed, finite, declarative business instructions**
for individual Privi IoT/Point of Position events. They give companies a way
to change **specific operating rules without deploying new arbitrary-execution
Solidity code** for every sensor or automated action. They are designed to
be more predictable and easier to restrict than an unrestricted smart-contract
language for **these bounded IoT workflows**, not universally superior to
smart contracts.

## What v1 actually does

Each one-hour-or-shorter Capsule must describe **one exact signed PoP event**,
the Privi chain and genesis, registered IoT contract, allowed company and
device, gateway wallet, company authorization epoch, unique 32-byte nonce,
event hash and position stamp, integer bounds over selected sensor fields,
and upper limits on **gas price, gas limit and worst-case test gas cost**.

The company's **current on-chain administrator** signs a deterministic EIP-191
challenge. Privi's development gateway validates that signature using
`ethers.verifyMessage`, verifies the current registered company and gateway
permissions on the ledger, enforces every declared integer predicate, checks
the pinned developer-chain block timestamp, and sends the IoT event with
the **actual signed gas transaction limits**. It returns an
`intentCapsuleDigest` alongside the regular signed IoT receipt.

A Capsule is **bound to the existing on-chain device sequence and PoP company/
zone position**, which are already unique. Replaying the same Capsule for the
same device event fails at the underlying ledger. After administrator transfer,
the next company authorization epoch invalidates previously signed Capsules.
A suspended company or revoked developer gateway cannot execute them.

**No arbitrary JavaScript, Solidity calls, loops, token transfer, treasury
access, balances, external bridges, or automatic PRVI mint** are in the
declarative Capsule grammar. Unknown fields fail closed. A Capsule cannot
choose another blockchain or bypass company consent.

## Developer usage

In an isolated valueless Privi developer gateway:

1. Deploy and pin the `PriviIoTLedger.sol` runtime. Register a developer,
   propose a company's account, require the company's independent wallet
   acceptance, and let the company authorize its developer gateway.
2. Produce and Ed25519-sign a PoP-v3 device event. Derive its exact
   `companyIdHash`, `deviceIdHash`, `eventHash`, and `popStampHash`
   using `packetDigest`.
3. Make a `capsule` object with every required field in `capsule.cjs`.
   The company administrator signs `intentMessage(capsule)` using their
   own EVM wallet `signMessage` operation. **Never paste company wallet
   private keys into GitHub, code, chat, or a hosted gateway.**
4. Set `config.requireIntentCapsules=true`, and submit with
   `submitEvent(packet,{...context,ethers,intentCapsule:{capsule,signature}})`.
   Submission rejects before signing the ledger transaction if the Capsule
   is missing, malformed, unauthorized or outside its signed limits.

The optional `requireIntentCapsules` gateway flag is mandatory to enforce
Capsules for *that gateway*. Other gateways, contract direct access and
unmodified consensus nodes are **not yet subject to this off-chain policy**.

## Real security and architectural limits

This is a working **development gateway feature** backed by an existing
Solidity IoT ledger for receipts. It is NOT a native Privi consensus opcode,
not financial mainnet, not an on-chain execution guarantee, and not a
replacement for ordinary smart contracts for arbitrary computation.

The EIP-191 admin authorization is verified against the current company
administrator at submission time; it does not prove real-world incorporation
or legal authority. Signatures are valid for an exact event but the system
does not maintain a standalone distributed nonce-consumption ledger. Runtime
revocation, block-timestamp checks, and fee ceilings occur in the gateway.
A malicious bypassing gateway could submit directly to the underlying IoT
ledger, so these checks **must move into the consensus application** before
they are advertised as native trustless Privi execution. Subsequent chain
reorgs/long-term time audit, alternate fee mechanics, multisig EIP-1271
accounts, policy version upgrades and cross-gateway replay auditing require
future work.

There is **no general security proof or independent audit** yet. The live
node still runs CometBFT, not genuine native PoP finality. Native bank
mint/balance provenance, a signed financial genesis, validator host attestation
and launch gates remain NO-GO. This feature does not issue a token or activate
the financial network.
