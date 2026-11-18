# Privi OutcomeGrid — Synthetic Proof of Concept

**Prelaunch. Synthetic records only. No real agents, customers, verified performance data, external integrations, payments, escrow, PRVI transfers, or mainnet activity.**

OutcomeGrid is a separate proposed Privi product for measurable AI-agent work and outcomes. Its potential long-term moat is consent-based verified outcome history, trusted buyer/verifier partnerships, and network distribution—not an uncopyable algorithm or guaranteed valuation.

## First prototype

- `core.py`: SQLite sandbox registry for measurable acceptance criteria, distinct buyer/executor/verifier roles, evidence SHA-256 digests, one accepted/rejected attestation per job, and a simple acceptance-rate scoreboard.
- `server.py`: public demo serving only four predefined synthetic fixture scenarios; it **does not accept customer job submissions or arbitrary verifier claims**.
- `test_core.py`: role separation, failed/self-attestation attempts, duplicate outcome prevention, concurrent retries, and score calculations.
- `test_server.py`: HTTP scenario tests and rejection of payment, arbitrary outcomes, and malformed inputs.

Run from repository root:

```bash
python -m unittest discover -s outcomegrid -p 'test_*.py' -v
PORT=10000 python outcomegrid/server.py
```

Then visit http://localhost:10000. No dependencies beyond the Python standard library.

## Security limitations

The `core.py` API uses synthetic *strings* for identities. They are **not authenticated credentials**. A production service must bind buyer/agent/verifier identities to signed, validated credentials and independent organizations. An arbitrary caller could forge the `actor` field if a public write API were added without real authentication. That is why the hosted server **only runs hardcoded fixtures** and does not expose public `post_job` or `attest` endpoints.

The evidence digest points to a **synthetic fixture**, not an actual successful CI run or validated third-party result. Evidence must be independently retrieved or signed from GitHub/test environments, checked against task-specific criteria, pinned to original commits, and corroborated by a human or separately authenticated executor where required. A verifier's attestation remains a claim unless the verifier is independently trustworthy.

For future use: implement real consent, provenance-aware evidence collection, identity/auth separation, disputes and appeal workflows, anti-Sybil/fraud rules, tenant isolation, data privacy and retention, reliable scoring with sample-size/confidence indicators, protected audit signing and independently stored checkpoints.

This should integrate with Privi ONE, Guard, CallProof and Ledger only after those services have verified sandbox interfaces. Do not mix any billing or wallet records with synthetic tests. No customer outcome data is currently being collected.

© 2026 Privi World Corp for original Privi-specific content, subject to third-party rights and existing licenses.
