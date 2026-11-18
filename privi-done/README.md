# Privi DONE + Code Origin — runnable offline first release

**Goal:** prove that an AI-agent software deployment meets explicit acceptance
criteria, and show which lines of source have *recorded* human/agent provenance.

This is a working **offline CLI**, not a live independently verified
deployment, paid product, or operational code-authorship detector.

## Run today (Python 3.11+, standard library)

```bash
python -m unittest discover -s privi-done -p 'test_*.py' -v
python privi-done/cli.py origin --source privi-done/cli.py
python privi-done/cli.py deployment --intent privi-done/examples/intent.json --evidence privi-done/examples/evidence.json
```

The code-origin command displays each line as **UNKNOWN** until there is
explicit, exact-file, exact-line claim evidence authenticated against an
independently pinned key. A signature can authenticate **who recorded a claim**,
not prove whether a human or an AI generated those lines. Human-edited AI code
can be mixed. Do not use these results to accuse employees of AI authorship.

The deployment command checks an exact repository and commit, complete required
checks, deployed version, synthetic probes and a budget bound. It returns
`PASS_PENDING_INDEPENDENT_VERIFICATION` for a passing local evidence snapshot,
not "verified complete". Caller-provided JSON can be fabricated.

## Path to paying service

1. Launch a read-only GitHub/Render adapter with authenticated, pinned account
   integration, trusted API checks, pagination and non-user-supplied evidence.
2. Compare a customer's agreed acceptance criteria to independently fetched
   version, health probes, tests and deployment cost; preserve signed receipts
   in an independent audit store.
3. Offer $19.99 human-reviewed outcome reports to consenting pilot customers
   after verified delivery capability. Do not enable an unattended paid
   checkout until actual fulfillment succeeds.
4. Add an agent IDE plugin that produces opt-in, signed line or patch-range
   authorship **claims** at edit time, tied to repo commit and a pinned signer.
   Record revisions rather than pretending that Git history proves authorship.
5. Audit privacy, retention, key rotation and false-positive risk before any
   enterprise use. Never require disclosure of private source to a public tool.

## Security boundaries

- No payments, tokens, mainnet, wallet access or external deployment actions.
- No independently authenticated GitHub/Render API retrieval yet.
- No on-chain Ledger receipt; the SHA-256 report digest is only a checksum.
- HMAC fixtures are for tests, not nonrepudiation or real signing-key custody.
- Privi ONE, Guard, CallProof, Ledger integration is a later gated step.

## Actual GitHub CI reporting (read-only)

The new `github-checks` command retrieves check runs directly from GitHub's
REST API over HTTPS, pinned to a full commit and explicit required check names:

```bash
# For public repositories, GitHub may allow anonymous reads at lower rate limits.
# For private repositories, provide a least-privilege read-only fine-grained token
# in GITHUB_TOKEN. Never paste the token into shell command arguments.
python privi-done/cli.py github-checks \
  --repository canoydario847-cloud/Privi-Network \
  --commit FULL_40_CHARACTER_SHA \
  --required "test-done"
```

This is **real source reporting**, but not an outcome certification. It validates
the GitHub API response for exact commit association, complete pagination,
duplicate check names, missing/pending/failed statuses and malformed payloads,
and rejects redirects rather than forwarding a credential. The report's
`REPORTED_CHECKS_SUCCESS_DEPLOYMENT_UNVERIFIED` result means that GitHub
reported the specified checks as successful. It does **not** prove a Render
deployment is accessible, that the required workflow belongs to a specific
trusted GitHub App, that cost claims were independently measured, or that
external actions occurred. A production verifier still needs independently
pinned check-app identities, a stable snapshot policy across retries, and
read-only Render deployment/health evidence.

This command never triggers a GitHub workflow, deploys code or writes to GitHub.
