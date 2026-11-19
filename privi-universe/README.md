# Privi Universe — Space-age navigation portal

**Prelaunch navigation only.** This is an independent, responsive web portal presenting Privi World Corp's AI infrastructure. No user accounts, pricing checkout, agent execution, wallets, models, or PRVI mainnet operations.

## Links and availability claims

- **Privi ONE:** known Render synthetic demonstration at https://privi-one-demo.onrender.com/
- **OutcomeGrid:** known Render synthetic demonstration at https://privi-outcomegrid-demo.onrender.com/
- **CallProof:** GitHub enterprise pilot scope document. **Not labeled as a verified live service.**
- **Privi Guard:** original GitHub implementation source. **Not labeled as a verified live service.**
- **Privi Ledger:** original GitHub implementation directory. **Not labeled as a verified live scanner/mainnet.**

There are no invented marketing links or fictitious online services. The portal's design is self-contained, dependency-free HTML/CSS in a standard-library Python HTTP server. It deliberately sends no tracking data to third parties.

## Local run and tests

From the repository root:

```bash
python -m unittest discover -s privi-universe -p 'test_*.py' -v
PORT=10000 python privi-universe/server.py
```

Open http://localhost:10000/ or query `/health`. Everything is read-only, with fail-closed unknown routes, CSP, and explicit product availability labels. Deploy on a separate **free** Render Python service with autoDeploy disabled, the same test build command, and `python privi-universe/server.py` as start command.

Visual style: CSS starfield, glowing orbital illustration, dark navy/cyan/violet mission control, responsive cards, reduced-motion support. Original Privi World Corp materials © 2026; "Made by Dario Canoy."

Next steps, after confirming published production endpoints: authenticate and test services independently, then promote reference links to live service cards only when verified. Do not connect real financial flows without separate authorization and security checks.

## Mission Status and Access Roadmap (November 19, 2026)

The portal now has a read-only **Mission Status** section that calls `GET /api/status`, backed by `status_monitor.py`. It observes only the fixed HTTPS `/health` URLs of the Privi ONE and OutcomeGrid Render sandbox demos. URL allowlisting, redirect blocking, bounded responses, strict expected-mode checks, timeouts, and a 90-second cache protect the public status interface. The response does **not** prove service uptime over time, security compliance, billing or payment availability, PRVI mainnet condition, or production readiness. It labels the other three modules source references (not monitored).

**Account Access** shows a transparent roadmap: Guests can open public demos, but real unified customer logins and Privi Pro entitlements are **not configured**. This is not an SSO implementation, and the website never collects passwords or grants paid privileges. Protected access must be enforced server-side after connecting a trusted OIDC provider and payment entitlement service, including verified revocation and tenant scope.

Tests mock health endpoints rather than relying on the internet and check that statuses never imply live production services. No paid infrastructure, production database connections, customer data storage, new accounts, Stripe actions, or PRVI operations were added.
