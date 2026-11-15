---
name: deep-think
description: Plan, test and review coding changes carefully on the first attempt; optionally record authorized USDC-paid revisions with Privi Call.
---

# Privi Deep Think — first-time-right coding skill for Codex and other coding agents

**Owner:** Privi World Corp. **Purpose:** reduce avoidable code defects through a requirements-first, test-first workflow. No tool guarantees zero mistakes or has access to a model's private reasoning.

**Pricing design:** First plan and first code snapshot review are free. A new, changed snapshot of the same task is a redo: the Privi MCP tool quotes **$0.01 USDC on Base via x402**. **Never sign or spend without explicit authorization from the human or account owner.** This is opt-in; it cannot compel unaffiliated Codex, Claude or Grok users to pay. Billing is not live until the service is deployed, CDP facilitator credentials and recipient are configured, subscription entitlements are reconciled, and a real settlement is verified.

## When to use

Use before implementing a nontrivial feature, bug fix, migration, integration or production deployment in Codex. The coding assistant should *internally* plan, use normal concise explanations, and write reliable code. Do not reveal hidden internal reasoning or invent verification results.

## First-time-right workflow

1. **Read first.** Determine the actual user goal, current architecture, interfaces, API versions, dependencies and expected tests. Identify missing requirements before editing.
2. **Define acceptance.** Write 2–10 clear, testable criteria, including no-regression behavior and security constraints. Identify rollback/recovery conditions.
3. **Plan before typing.** Consider minimal design, failure modes, concurrency, validation, privacy/secrets, negative cases, version compatibility and cost. Choose the smallest change that works.
4. **Start Privi record (optional).** Connect to the Privi Call MCP endpoint and call `deep_think_plan(goal, language, acceptance_criteria)`. Store the returned `task_id` and `task_token` privately (never in source, git commits, prompts to third parties, or logs). Do not send code or secrets; the server stores a hash of the goal.
5. **Write one coherent patch.** Check existing tests and conventions, implement only scoped changes, update docs if the interface changed. Do not silently widen privileges or add dependencies.
6. **Independently verify.** Run language syntax/type checking, focused unit tests, edge-case tests, security checks and integration tests available in the user's repository. Review the complete diff for leaks, broken compatibility and unintended edits. If a check could not run, mark it **false**, not passed.
7. **Hash your snapshot locally.** Produce a lowercase 64-character SHA-256 digest of the *actual changed code snapshot*. For a single file, use `sha256sum path/to/file` where available. For a multi-file change, deterministically hash sorted relative paths and file bytes; include newly created files. Do not send raw source to Privi.
8. **Submit first attempt (free).** Call `deep_think_review(task_id, task_token, source_sha256, checks)`. The five required boolean checks are `syntax`, `tests`, `edge_cases`, `security`, `integration`. They are self-reported evidence, not independently verified by the server. Report the actual command outputs and failures to the customer.
9. **If a correction is needed:** Explain the issue to the account owner. Before requesting any redo payment, determine whether the code snapshot really changed. If it did, call `deep_think_redo(task_id, task_token, prior_sha256, new_sha256, approve_usdc_charge=true)` *only after explicit customer authorization* and with an owner-approved x402 payment payload in MCP `_meta["x402/payment"]`. A missing payment yields PaymentRequired. **Do not retry payments blindly after an ambiguous settlement**; reconcile using a transaction receipt first. If the user has an unlimited plan, confirm its entitlement before taking an extra fee.
10. **Finish accurately.** State files changed, actual tests run/passed/failed, unresolved risks, billable redo count, and only verified on-chain settlement references.

## Tools exposed by Privi Call after deployment

| MCP tool | Function | Price |
|---|---|---|
| `deep_think_plan` | Create requirements-first checklist and one-time task token | Free |
| `deep_think_review` | Record first code hash and self-reported test checks | Free for same task's first snapshot / same-hash rechecks |
| `deep_think_redo` | Record a changed snapshot only after signed x402 settlement | $0.01 USDC per authorized changed snapshot |

MCP endpoint candidate: `https://privi-call-e3rb.onrender.com/mcp` **only after deployment is confirmed**. Source: `call-server/src/privi_call/deep_think.py` and `deep_think_tools.py`.

## Payment and privacy rules

- No wallet keys, raw code, API tokens or prompts sent to the Privi ledger. Task secrets are hashed in SQLite and must never be pasted into public issues.
- The billing server does not automatically charge a model for every edit in Codex. It can only meter revisions submitted by opted-in clients with an authorized wallet. It cannot detect revisions performed outside its integration.
- A genuine redo must change a recorded SHA-256 fingerprint. Same-hash retries are free; stale state, invalid token, payment-replay and failed settlement do not create a valid redo.
- Every successful charged redo must have a Base transaction hash that can be reconciled. A payment receipt alone is not proof of external customer revenue; verify USDC transfer and customer attribution.
- If a task was completed incorrectly, always fix it; never hide failures to avoid fees. Refund disputes and unlimited-plan billing rules require a production policy before commercial rollout.
- Treat test pass flags as self-attestations. This skill reduces risk but does not certify code correctness, security, or deployment safety.

## Local acceptance gate

Run `python -m pytest call-server/tests/test_deep_think.py -q` from repository root after installing `call-server` development dependencies. Re-run the Call server regression suite before merging. Do not claim live payments without a documented authorized Base USDC settlement.
