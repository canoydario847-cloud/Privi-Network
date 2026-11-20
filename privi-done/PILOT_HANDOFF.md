# Privi DONE — Customer pilot handoff

**Made by Dario Canoy | Privi World Corp | Prelaunch**

## Offer: one no-cost, human-reviewed pilot

Privi DONE helps deployment owners answer: *Did the specified release actually reach the intended service and pass the checks we agreed on?*

We are offering an **initial no-cost assessment** of one sandbox or non-critical deployment to a consenting design partner. This is a prelaunch test, not a guarantee of security, uptime, cost savings or regulatory compliance. No unapproved changes to the customer's systems; no token or wallet activity.

### What a pilot customer provides

- Written permission from the owner of the **specific deployment** to run read-only observations, including the target service, environment and allowed endpoints.
- A GitHub repository, immutable expected commit and **named required checks** agreed in advance, with access granted only when necessary.
- A test-only service or preview (no production secrets), plus an agreed list of expected responses and acceptable latency/time window.
- Optional **redacted** cost information and a spending threshold. No billing credentials.
- A single responsible human who can review the evidence and explicitly accept or reject the scoped deliverable.

**Do not post access tokens, private source, personally identifying data, wallet keys, customer URLs containing secrets, or proprietary business details in a public GitHub issue.** Exchange sensitive materials in an approved private channel after consent.

### Definition of completion — agreed before testing

The pilot is ready for customer review only when the reviewer can trace:

1. Service identity and pinned commit to authorized provider metadata.
2. Results of every explicitly required CI check without skipped/pending/failed critical checks.
3. Externally observed test behavior from approved endpoints, with timestamp and error/cold-start details.
4. Evidence gaps and limitations, including unverified prices, unsigned records and uncertain authorship.
5. Customer signoff recorded separately by an authorized customer representative.

**No automated billing, settlement, financial mainnet activity, or “verified complete” status is allowed based solely on a passing health endpoint or provider response.**

## Demonstration already available

- [Live company-owned sandbox preview](https://privi-done-version-preview.onrender.com)
- [Privi DONE draft PR #318](https://github.com/canoydario847-cloud/Privi-Network/pull/318)
- [Four-endpoint internal verification evidence](./reports/read-only-functional-preview-2026-11-19.md)
- Fixed internal scope: `examples/internal-pilot-scope.json` for `7d4299ab717e7cbd13344b1950127f574836d3dc`

The internal scope has been checked against live fixed-endpoint observations. **This is an internal pilot, not acceptance from a paying customer.** The generic customer support layer is **not yet** equipped to fetch arbitrary customer endpoints safely; future customer-specific integrations require allowlisted targets and threat-model review.

## Future pricing

Proposed $19.99 one-time human-reviewed report **only after demonstrably fulfillable delivery** and explicit customer price consent. No live checkout, automatic charge, or payment-verification claim is part of this pilot.

## Contact script for an invited design partner

> We are testing Privi DONE, a deployment evidence review that compares a pinned GitHub commit, required build checks, and externally observed service behavior. Would you be open to one **free**, non-production pilot on a deployment you own? We will agree on the read-only checks in writing first, provide a clearly limited evidence report, and ask you to approve or reject the result. No production access or payment is required for this first test.

## Pilot status

**Ready to invite a consenting design partner; not yet ready for general paid self-service.** A verified provider-response report is not the same as a verified customer outcome.

## Request a free pilot (public information only)

Prospective design partners can [open a Privi DONE pilot-interest issue](https://github.com/canoydario847-cloud/Privi-Network/issues/new?template=privi-done-free-pilot.yml) after the pilot intake template is merged to the repository's default branch. GitHub generally loads issue forms from the default branch, so **the template is not publicly usable while it exists only in draft PR #318**.

The issue asks only for a public organization/project name, non-production
environment, desired review goal and non-sensitive acceptance criteria.
It explicitly prohibits posting secrets, private customer data or credentials.
Do not perform work or contact deployment systems until the owner agrees to a
limited written scope. Never infer customer acceptance or purchase from
submitting an issue.
