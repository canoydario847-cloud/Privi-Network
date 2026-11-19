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

## Render deploy metadata: read-only operational integration

Use a least-privilege Render API key that can read an approved service. Never
paste credentials into chat, command arguments, source files or CI logs. The
Render account connector also requires explicit workspace selection before
reading the owner's account; this prototype does not choose one.

```bash
export RENDER_API_KEY="set-securely-outside-the-repository"
python privi-done/cli.py render-deploy \
  --service-id srv-YOUR_PINNED_SERVICE_ID \
  --repository OWNER/REPO \
  --commit FULL_40_CHARACTER_SHA
```

This command performs *only* Render API GET requests (service metadata and
recent deploys). It rejects redirects, unpinned repository/service identities,
stale or ambiguous live commit matches, and incomplete responses. It does not
perform arbitrary HTTP health probes, release a deployment, or retrieve costs.
Render's `live` status and correct commit mean **reported deployment metadata
only**, not that the application is healthy, safe, available to customers,
or that a real purchase was delivered. Compare this result with GitHub checks
and separately approved acceptance probes before offering a verified outcome.

The example tests use injected JSON fixtures, not customer deployments.

## One-command customer-readable provider report

Once you have an **authorized** Render service ID, exact GitHub repository and
commit, and read-only API credentials, generate a local Markdown report:

```bash
python privi-done/cli.py provider-report \
  --repository OWNER/REPO \
  --commit FULL_40_CHARACTER_SHA \
  --service-id srv-YOUR_PINNED_SERVICE_ID \
  --required "build" \
  --required "security" \
  --output privi-done-report.md
```

The output explicitly marks GitHub-check and Render-deployment match status,
then lists **three outstanding requirements**: independent service health,
verified cost and customer acceptance. Even matching provider reports must
**never** authorize a customer charge or a completed-work certificate.
The digest is a checksum, **not a signed Ledger receipt**.

### Next live pilot gate

Use a consenting deployment owner and the correct Render workspace to perform
the first read-only end-to-end run. Before handing a report to a customer,
verify the expected version and health from a separately authorized, controlled
probe, then have the customer confirm agreed acceptance criteria. Do not add
a generic user-supplied health URL to a server-side fetcher (SSRF risk).
Render connector access currently requires a workspace selected by the owner;
no workspace, key, or account service has been selected by this PR.

## Fixed public sandbox health observation

A separate read-only command checks ONLY the Privi ONE sandbox's fixed
`https://privi-one-demo.onrender.com/health` endpoint:

```bash
python privi-done/cli.py privi-one-health
```

In the combined customer report, add `--with-privi-one-health` to include
this optional observation. It cannot access arbitrary customer URLs and never
follows redirects. The observer checks the documented
`ok: true`, `service: privi-one-demo`, `mode: PRELAUNCH_SIMULATION`
response; timeouts, unexpected bodies, redirect attempts and errors fail
closed. A successful observation **does not authenticate a specific Git
commit**, demonstrate the customer's app, or verify pricing. Customer
acceptance and independently verified outcome remain pending.

Use company-approved allowlisted endpoints for any later expansion, with DNS
pinning/SSRF protections, restricted protocols and private-network denial.
Do not replace the fixed endpoint with unconstrained user-supplied URLs.

## Render free-tier cold-start investigation (November 19, 2026)

Authorized Render inspection of `privi-one-demo` showed its latest deployment
`dep-dbv1lgu7bikc73f9vm3g` marked `live`, commit
`064b3fdc6c0310b0d55b9d7ec501ec4f5bbc78f2`.
The first two external `/health` probes received HTTP 502 (~9.9s) and HTTP
503 (~10.0s); Render's Python startup log appeared immediately afterward.
A free-instance cold start is a plausible explanation, **not yet proven**.
This is not sufficient to infer a code defect or certify availability.

The fixed-endpoint observer now allows two bounded attempts of up to 45
seconds each. Persistent failures remain `HEALTH_UNAVAILABLE`. No deployment
settings, paid plans, mainnet, wallet, or billing code are changed. Avoid using
this extended timeout for latency SLOs: separate uptime measurements must
record both slow cold starts and failed probes.
