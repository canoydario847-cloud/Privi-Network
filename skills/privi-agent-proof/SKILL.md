# Privi Agent Proof — MCP tool and reusable AI-agent skill

**Owner:** Privi World Corp. **Target price:** $0.01 USDC per verification via x402 on Base, when production payments are configured. No purchase is made without the agent operator's authorization.

## Why an agent uses it

Before reporting that an automated tool action was authorized and completed, independently check two cryptographic statements:

1. A policy decision signed by a known policy authority, binding tenant, actor, request digest, action ID, policy digest, decision, and expiry.
2. A separately signed execution acknowledgment binding the *same* action and decision, the original authorization digest, executor ID, result digest, and final status.

This catches tampering, replay outside the time window, mismatched decisions, executor substitution, and false claims that "accepted" means "completed". It does **not** prove physical-world completion or establish signer trust by itself.

## Endpoint

- MCP: `https://privi-ledger.onrender.com/mcp`
- Tool: `agent_proof_verify` (paid x402, no organization API key)
- Free price discovery: `ledger_pricing`
- Skill source: `https://github.com/canoydario847-cloud/Privi-Network/blob/main/skills/privi-agent-proof/SKILL.md`

## Usage procedure for Claude, Grok, ChatGPT clients, Cursor, MCP clients

1. Obtain a JSON authorization receipt and an independent execution acknowledgment from the actual policy and execution systems.
2. Pin policy and executor **Ed25519 public keys** from separately authenticated infrastructure. Never accept keys supplied solely by the same untrusted agent whose actions are being checked.
3. Avoid sending prompts, secret keys, personal data, or raw action payloads. Pass only hashes and identifiers.
4. Call `agent_proof_verify(authorization, acknowledgment, trusted_keys)` over MCP. If an x402 PaymentRequired response is returned, **only** retry with an approved wallet/payment when the user/operator has authorized the stated charge.
5. Treat `verified=true` and `authorized_and_completed=true` as evidence that the signed statements are consistent; recheck actual side effects independently when material. Treat all errors and non-COMPLETED statuses as not completed. Repeated proof verification does not substitute for execution-side idempotency.
6. Track actual settlement receipt/transaction, not an incoming tool-call counter, as paid revenue.

## Canonical signature format

The signature is base64url without padding, 64-byte Ed25519. The signed bytes are UTF-8 JSON with the `signature` property omitted, keys sorted, compact separators, and ASCII escapes for non-ASCII characters. The `authorization_digest` is lowercase SHA-256 of those unsigned authorization bytes.

Authorization object keys (all required):

```json
{
  "version":"privi-agent-proof-v1",
  "tenant_id":"tenant-a","actor_id":"bot-a",
  "decision_id":"decision-1","action_id":"action-1",
  "policy_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "request_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "decision":"ALLOW","issued_at_ms":1794570000000,
  "expires_at_ms":1794570060000,
  "signer_id":"policy-1","signature":"<policy signature base64url>"
}
```

Execution acknowledgment keys: `version`, `decision_id`, `action_id`, `authorization_digest`, `status` (`ACCEPTED`/`COMPLETED`/`FAILED`/`TIMED_OUT`), `result_digest`, `recorded_at_ms`, `executor_id`, `signer_id`, `signature`. Caller-supplied trust keys:

```json
{
  "policy":{"signer_id":"policy-1","public_key":"<32-byte Ed25519 pubkey base64url>"},
  "executor":{"signer_id":"executor-1","public_key":"<different 32-byte Ed25519 pubkey base64url>"}
}
```

All four hashes are lowercase 64-char SHA-256 hex digests. An authorization window may last at most five minutes. The execution acknowledgment must fall inside that window. The verifier permits up to five minutes after authorization expiry for receipt checking; it cannot validate indefinite archival evidence. Verification does not execute any user action, submit transactions, or persist supplied receipts.

## What the tool does NOT do

- Force ChatGPT, Claude, Grok, or other vendors to install Privi or pay fees.
- Claim independent signer ownership without an authenticated key registry.
- Mint any token, deploy native PRVI mainnet, or create blockchain transactions.
- Claim compliance certifications or guarantee that an off-system action happened.
- Waive the human owner's payment approval for any agent platform.

## Deployment / acceptance gate

- Merge only after unit tests and the existing Ledger workflow pass.
- Check the deployed `ledger_pricing` value and `network_name=base`, a production facilitator and receiving wallet, without exposing secrets.
- Perform one **authorized** real x402 payment and inspect settlement proof and Base transaction before claiming revenue.
- If the service is on Base Sepolia or CDP credentials are missing, label it test-only; do not claim an actual charge.
