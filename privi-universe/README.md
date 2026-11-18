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
