# Privi Global Agent Network — launch and latency plan (2026-10-26)

Copyright (c) 2026 Privi World Co. All rights reserved. Founder: Dario Canoy.

**Status: engineering and submission plan only. No claims of completed third-party submissions, cloud deployments, billable users, quantum hardware access, or revenue.**

## Products already in the repo

- Privi Call: agent directory, remote MCP routing, warm HTTP connections, x402 prepaid packs (see [call-server](../call-server/README.md)).
- Privi Quantum: classical statevector simulator for QAOA up to 16 qubits, OpenQASM export, PQ signature/verification ([quantum-server](../quantum-server/README.md)). **Not quantum advantage or accelerated inference**.
- Privi Ledger / Guard / Verify: audit, trust, and supply-chain integration tools.
- Existing discovery service: A2A card, MCP manifest and llms.txt. Listing or endpoints do not establish availability: confirm health and a live MCP initialize/tools/list roundtrip.

## What to sell first

1. Free: read-only MCP onboarding, guard/verification demo and trial calls.
2. Pay-per-call: Privi Call already documents 50 free non-Privi calls per day, then $0.001/call from prepaid $1 packs of 1000 through x402. **Confirm Coinbase CDP keys, facilitator, wallet routing, fulfillment, replay/idempotency and actual settlement before offering this publicly.**
3. Stripe LIFE credits: live Stripe account exists but the LIFE 100-credit product is inactive and marked fulfillment_status=not_connected. Do not activate or publish a checkout until webhook signature verification, payment.completed fulfillment, durable credit ledger, refund/chargeback and replay protections pass.
4. Never equate token sales to SaaS credits; no investment or earnings promises. Keep native PRVI financial mainnet and BNB PRIV separate.

## Agent targets — prospective integration partners, NOT active partners

- MCP developers who expose public HTTPS, implement initialize and tools/list, and use the official registry.
- Teams shipping LangGraph, CrewAI, AutoGen, and FastMCP agent systems (invite to add Privi Guard and Privi Call; no affiliation claimed).
- Factory planning/quality-control software developers who can evaluate balance_lines, select_lots and split_conflicts on *small* datasets, compare with exact classical optimizers, and supply written feedback.
- x402-capable agent developers exploring paid tool calls. One free pilot request per developer; no bulk unsolicited messages.

## Global publication destinations, with concrete next action

These are **destinations, not completed submissions**. Follow each site's own content / anti-spam rules. Use localized tutorials and real demonstrations rather than repeatedly posting an advertisement.

| Market | Channel | Action |
|---|---|---|
| Worldwide | Official MCP Registry (https://modelcontextprotocol.io/registry/quickstart) | Verify live endpoints, version server.json; publish via existing GitHub Actions OIDC workflow; inspect its run and registry record |
| Worldwide | Glama (https://glama.ai/) | Claim / submit canonical repo and check tool metadata |
| Worldwide | Smithery (https://smithery.ai/new) | Confirm submission support and live streamable-HTTP compatibility |
| Worldwide | mcp.so (https://mcp.so/submit), mcpservers.org (https://mcpservers.org/) | Submit only after health, licensing, and readable MCP examples are verified; check for fees before opting in |
| China | ModelScope MCP ecosystem (https://modelscope.cn/), Gitee (https://gitee.com/) | Mandarin technical intro and demo; assess marketplace eligibility, hosting/legal/data-transfer requirements, and local partner first |
| Japan | Qiita (https://qiita.com/) | Japanese hands-on article: connect an MCP client, run a read-only tool, compare simulator with classical optimizer |
| Brazil / S. America | DEV Community (https://dev.to/) and local developer meetups | Portuguese-language proof-of-use guide; invite Brazil-based agent builders to a pilot |
| Mexico / Spanish LATAM | DEV Community (https://dev.to/) and local developer communities | Spanish MCP installation + free pilot; avoid assumed community endorsement |
| Africa | DEV Community (https://dev.to/) and African AI/developer meetups | English-language developer pilot, offer low-bandwidth MCP usage guides; ask about access and local requirements |
| UK | DEV Community (https://dev.to/) and UK AI developer meetups | English integration guide focused on Guard/Call/Verify rather than unverifiable speed claims |

## Regional compute locations (candidate only; **none provisioned here**)

AWS publishes Tokyo ap-northeast-1 (Japan), Mexico Central mx-central-1, São Paulo sa-east-1 (South America), Cape Town af-south-1 (Africa), and London eu-west-2 (England). For China, Beijing/Ningxia are separately operated with separate AWS China accounts and local compliance requirements. AWS is a reference map, **not a claim Privi has AWS resources**. Costs, access, feature parity, and compliance must be checked before spending.

Start with a single healthy origin and regional measurements. Only add deployment replicas after actual latency/cost measurements show benefit. Store personal data in suitable regions subject to applicable law.

## Low-latency architecture (not quantum advantage)

Client -> closest edge/router -> authenticate and check spending mandate -> select responsive agent -> HTTP keepalive pool -> MCP tools/call -> metered ledger + signed receipt -> client.

- Route independently runnable calls concurrently using bounded fan-out; cap overall spend, queue depth, and wall-clock budget. Do not parallelize dependent or unapproved actions.
- Cache metadata/tool lists with explicit TTL and safe invalidation; do not cache personalized answers across tenants.
- Reuse warm connections and minimize cross-region roundtrips.
- Report p50/p95/p99 end-to-end latency, tool failures, region, cold-vs-warm, concurrency, token cost, and **actual** settlement IDs. No synthetic metrics in public marketing.
- QAOA is suitable for tiny optimization demonstrations, not a faster language model. Only benchmark true hardware if an authorized cloud quantum provider is connected and compare against state-of-the-art classical solvers.

## Regional smoke and latency measurements

Run the probe from an actual VM in each candidate region; the region label is user-provided, not geolocated or verified. The script measures HTTPS /health request latency, **not** MCP tool execution or quantum speed. Verify MCP separately with initialize and tools/list.

~~~bash
python call-server/tools/latency_probe.py --region ap-northeast-1 --url https://privi-quantum.onrender.com/health --url https://privi-call.onrender.com/health --requests 20 --workers 4 --output privi-tokyo.json
~~~

Do **not** assume a failed web crawler GET /mcp proves the MCP service is down; streamable-HTTP implementations can respond with 405 to GET. Use /health and a protocol-correct MCP POST test. Never expose API keys in probes.

## Launch gates

- [ ] Confirm each endpoint health and successful JSON-RPC MCP initialize/tools/list.
- [ ] Confirm official registry names and verified publication workflow results.
- [ ] Publish accurate English / Japanese / Mandarin / Spanish / Portuguese guides once each.
- [ ] Obtain partner opt-in; log number of genuine external agent integrations and activated customers.
- [ ] Demonstrate idempotent, settled x402 purchase and correct credit deduction, or a separate end-to-end Stripe fulfillment test **before** live sale.
- [ ] Benchmark before claiming speedups; record measured p95 from at least two geographies.
- [ ] Review privacy, tax, sanctions/export controls, and China-specific hosting/ICP considerations before regional infrastructure changes.
