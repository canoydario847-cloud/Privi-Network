# Render workspace cutover — November 14, 2026

Destination: Privi workspace tea-dbr1aqjrjlhs73ccmcbg.

Every one of the 25 services inventoried in the billing-suspended old account has a same-name counterpart in the destination. This confirms resource recreation only, not state migration. Core Ledger, Verify, Anchor, Call, Quantum, Wallet and TEST devnet responded with HTTP 200 at the new mapped health endpoints. Static replacements served HTTP 200. Discovery and Jose served HTTP 200. The evidence demo root returns 404 and requires a separate route check.

This change updates current website links, discovery metadata, Jose service-health probes and runtime service defaults to the destination URLs listed in render-cutover-map.json. Historical documents, issued receipts and signing material are not rewritten. Eight existing services have their public URL environment variables merged to the destination values without replacing existing secrets. Wallet's Ledger URL also points to the destination.

Outstanding before claiming full migration:
- Compare original and destination SQLite/Postgres records, org/user IDs and row counts from secure backups. Verify receipt roots and last sequence/hash. No such comparison has been completed here.
- Securely preserve and reconcile validator, attestation, session and signing-key identities. Do not generate replacements and call them migrated. Do not expose private material in GitHub or chat.
- Reconcile credits, API keys, webhook registrations, OAuth callback allowlists and permissions separately. No successful payments, issuance or mainnet readiness is claimed by HTTP health checks.
- Confirm desired custom-domain ownership and DNS cutover. Old onrender.com names remain owned by the suspended account and are not transferred by these changes.
- The extra destination service named Privi (srv-dbro2l3bc2fs73cmrqv0) was repaired: build now installs agent-gateway dependencies and start runs node agent-gateway/server.js. Render deployment dep-dbsc7afj5k9c73eo0ae0 is live; /health returned HTTP 200 with paid_only=true and public_demo_enabled=false. Payment fulfillment remains unverified.

No old service, disk, key or database is deleted. No paid tier changes are made. New deployments must be checked to terminal live status, then verified against their actual service identity. A recreated devnet is valueless TEST, not native financial mainnet.

Cutover verification: merged release 10001e3717a68dbc8142612e7b3154c10d3e19f8 reached live status for all 22 main-branch destination services in scope. Jose subsequently reported grade A with 5/5 service health responses. All 19 CI checks passed. The separately deployed Car Trace branch had its remaining Hub URL corrected at 3042edecad7f815db35ddaf039f359587236f031, and served HTML was checked. render.yaml now preserves the destination origins during future Blueprint syncs.
