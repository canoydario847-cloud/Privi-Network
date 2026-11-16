# Privi CallProof — Enterprise Agent Trust Pilot

**Product:** Privi CallProof — Trust Every AI Agent Call  
**Company:** Privi World Corp  
**Public product and 25-second demo:** https://privi-ai-21-gateway.onrender.com/callproof  
**Interactive synthetic demo:** https://privi-ai-21-gateway.onrender.com/callproof/demo  
**AI-agent integration skill:** https://privi-ai-21-gateway.onrender.com/callproof/SKILL.md  
**Contact:** canoydario847@gmail.com

## Problem worth an enterprise pilot

As AI agents gain access to tools, the same action can be requested from multiple assistants, over retried MCP calls, and without clear human approval or a durable record of which agent requested it. When that action changes a CRM, deletes a file, sends a message or spends money, ambiguity is unacceptable.

Privi CallProof proposes a **vendor-neutral control and evidence layer** in front of agent-to-tool calls. It complements Model Context Protocol (MCP), agent orchestration frameworks and A2A collaboration rather than replacing them.

## Working v0.8 deliverables

| Control | Implementation | What it does NOT prove |
|---|---|---|
| Scoped delegation | Separate short-lived agent capabilities with an exact tool allowlist | Not OAuth/OIDC or a cross-company identity federation |
| Budget gate | Atomic PostgreSQL call-count and estimated cost policy reservations | Policy cents are NOT actual billing, nor payment settlement |
| Retry-safe intent | Unique idempotency key per delegated agent grant | External executor must also enforce idempotency |
| Human write approval | Separate verified Privi Pro owner credential | No autonomous agent may approve itself with its limited capability |
| Signed evidence | Ed25519 signature over executor-reported output, input hashes and prior receipt hash | Not independent proof of third-party execution or PRVI blockchain finality |
| License access | Active $35 one-time Privi Pro Unlimited wildcard entitlement rechecked at use time | Checkout does not instantly issue an API key |

The public website and simulated interactive demo have been deployed. Pro-only production runtime remains **disabled until its backed-up database, verified Stripe entitlement webhook, signing key, operator token, and security validation are configured**. Offline GitHub integration tests exercise the database-backed flow.

## Suggested buyer profile

Target engineering managers and platform security teams building:
- Enterprise AI agent tool-call gateways and MCP infrastructure
- Customer support and CRM automation that includes write or delete actions
- Financial operations agents requiring approval before sensitive actions
- Developer platforms operating multiple AI models and vendors

Do **not** imply Privi has signed agreements with OpenAI, Anthropic, Microsoft, Amazon, Google, xAI or other technology companies. They are potential customer segments, not reference customers.

## Four-week opt-in design partner pilot

**Week 1 — Scope and security:** agree on one narrow tool workflow, roles, credential distribution, external executor boundaries, threat model, retention limits and pilot acceptance criteria.

**Week 2 — Integration:** connect a test agent via MCP or HTTPS, issue one scoped Pro entitlement and two segregated role credentials; build an independent executor adapter with its own idempotency enforcement.

**Week 3 — Faults and evidence:** test forbidden tool access, approval bypass attempts, concurrent retry collisions, token revocation, refund/dispute revocation, output tampering, tenant isolation, external service failures and signer/DB failures.

**Week 4 — Buyer review:** present measured policy decisions, response latency, retry handling, denial counts, signed evidence exports and unresolved risks; provide an implementation and procurement plan if the pilot demonstrates value.

## Suggested acceptance criteria for a paid contract

1. **Unauthorized requests denied:** Every predefined out-of-scope tool or unapproved write is denied by the Privi policy service in the test matrix.
2. **Retry safety:** At least 100 concurrent duplicate policy-intent requests create at most one durable reservation, with no budget overrun.
3. **Recorded evidence:** Every accepted executor report is cryptographically verifiable; modified receipts fail verification; receipt sequence gaps and changed previous hashes are detected in audit procedure.
4. **Separation of duties:** The agent capability cannot approve writes or submit executor reports; the executor cannot generate new grants.
5. **Revocation:** Revoked agent tokens, Pro entitlements, or expired grants cannot reserve or report new actions.
6. **Operational data:** Publish test-environment latency, error/availability rates and failure-injection results; do not promise an SLA until measured.
7. **Compliance and procurement:** Assess pen test, SSO/OIDC, retention, deletion/export, data processing terms, SOC 2 readiness, key custody, backup/restore and subprocessor reviews before enterprise production use.

## Commercial packaging

**Developer adoption:** $35 one-time Privi Pro Unlimited covers the current CallProof feature and the entire Privi service catalog. User education and demos are public; runtime access requires verified fulfillment.

**Enterprise contract:** Separate pilot/implementation, SSO, dedicated infrastructure, integration support, data processing, SLAs and security requirements must be scoped and priced by written agreement. No enterprise fee or million-dollar revenue is represented as secured today.

**First sales CTA:** "Let's pick one risky AI-agent tool call, make it policy-controlled, require approval, and demonstrate a signed executor-reported receipt on your own test system."

**Email subject:** Safer MCP/AI agent tool calls — scoped four-week CallProof pilot

**Short email body:**
Hello,

We are developing Privi CallProof, a vendor-neutral AI-agent tool-call control plane. It supports scoped permissions, retry-safe authorization, spending-policy ceilings, separate approval for high-impact actions and Ed25519-signed executor-reported receipts.

We have published a live product website and a transparent simulated demo: https://privi-ai-21-gateway.onrender.com/callproof

We are seeking one design partner with a real MCP or AI-agent workflow involving a sensitive write. The proposed pilot would test security boundaries, retries, approvals and evidence against agreed acceptance criteria. Production execution is not yet generally available, and we'd scope infrastructure/security requirements before integration.

Would your agent platform or security engineering team be open to a short technical scoping conversation?

Privi World Corp
canoydario847@gmail.com

## Go-to-market rules

- Honor an overall $1,000/month **maximum** previously authorized marketing budget. This does not by itself authorize a specific paid ad campaign or vendor.
- Do not use mass unsolicited email or post in communities that ban commercial promotion.
- Send users to the flagship website and video first, then the simulated interactive demo, then a pilot inquiry.
- Keep the old Privi products available as supporting services, not the company's primary positioning.
- Do not advertise guaranteed cryptographic security, external action completion, privacy compliance, mainnet launch, quantum performance, or revenue results.

**Owner:** Privi World Corp. © 2026. This is a product/pilot proposal, not a signed contract or a claim of verified paying enterprise customers.
