# Privi-native enterprise access policy (opt-in)

**Objective:** Make Privi the default and required settlement blockchain for
companies that choose the **official Privi IoT / AI / PoP ledger services**.

**Limits:** This policy governs only software, smart contracts, integrations,
credentials, and user agreements owned or licensed by Privi. It cannot make
Privi the sole blockchain used by every company worldwide, prohibit external
software or blockchains, or automatically bind companies that never opt in.
The published PoP paper identifies a CC BY 4.0 license. Contract,
competition and intellectual-property claims require independent legal review.

## Enforced now in developer code

1. A company identifier is hashed as \`SHA256(UTF8(companyId))\` and
   onboarding is **proposed** by the Privi administrator. Only the separately
   designated company administrator may explicitly **accept or reject** the
   pending invitation. Pending proposals grant no IoT rights.
2. After acceptance, only the company administrator authorizes individual
   **Privi-registered developer gateway** addresses for that company.
3. Devices are enrolled only after **both** company and developer are active
   and the company has authorized that specific gateway.
4. Each data transaction must pass company status, company-approved gateway,
   developer status, device enrollment, signed packet validation and unique
   company-zone PoP position checks. Refuse closed on any failure.
5. Administrator-suspended companies and revoked company gateways cannot submit
   any further events. Reactivation requires explicit authorized actions.
6. Settlement uses only the chain ID, native genesis and deployed contract
   bytecode pinned to the Privi configuration. No BNB, Base, Ethereum, bridging,
   token pairing, or automatically minted PRVI can substitute for registration.
7. Raw device data remain off-chain by default; local AI labels metadata and
   proposed, non-redeemable PoP-based micro-PRVI accounting values.

These are the enforceable **official feature access controls**. A pending
invitation MUST NOT be counted as a company adoption or activation. The current
reference EVM ID 262144 is a disposable development network, NOT final Privi
PoP mainnet. Real PRVI issuance and financial network activation stay blocked
until audited native PoP consensus and financial safety gates are complete.

## Company control and safe handover (development design)

A company's current registered administrator must propose any new administrator,
and the proposed successor must accept the transfer from the successor wallet.
The Privi platform operator is never a substitute for the company's approval.
The old administrator may cancel an unaccepted proposal.

A successful transfer advances the company's gateway-permission epoch. This
invalidates all gateway permissions granted by the previous administrator in
constant time, without iterating across unknown devices or operators. The new
administrator chooses which Privi-registered gateways to reapprove.

This design **does not recover lost administrator keys**. Enterprise recovery
requires verified organizational identity, predefined multisig/guardian
governance, independently audited emergency procedures and legal process.
Do not permit a unilateral platform-owner takeover or bypass consent on
the basis of a support ticket, self-declared corporate title, or payment.

## Enterprise adoption plan (proposal, not a guarantee)

Offer developer documentation, self-service company onboarding, APIs,
contract-backed audit trails, privacy-preserving device management, uptime
monitoring, transparent data exports, optional service-level agreements,
and clear, voluntary enterprise pricing. Companies that adopt the official
service can make Privi their only blockchain *for these particular workflows*.
Their unrelated business systems and outside blockchain choices remain theirs.

Track progress by voluntarily enrolled companies, retained active integrations,
verified PoP transactions, data reliability and independent operator trust.
Avoid claiming universal adoption, guaranteed profits, compulsory participation,
ownership of public concepts, or real PRVI data payouts from speculative values.

## Security and governance still required

- Replace centralized owner with security-reviewed role controls/multisig
  before real production deployment; independent tenant identity checks.
- Device authenticity, billing, quotas, sybil/spam controls, data retention,
  confidentiality and customer revocation/export/privacy obligations.
- PoP validator BFT consensus implementation, native 1B PRVI supply integrity,
  no direct bank/KV bypasses, independent audits and actual operator testing.

This policy is a product implementation goal. It is not a legal opinion or
a claim that any company has already signed up or switched blockchains.
