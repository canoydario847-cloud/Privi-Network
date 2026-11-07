# Privi Agent Exchange — real-time agent directory

Status: architecture and deployment specification; not yet a live service.

## Product
Privi Agent Exchange is a registry and execution gateway for AI agents, tools and computational backends. Public agent discovery is free; authenticated, metered tool execution is paid. Avoid claims of universal agent adoption or quantum speedups.

## API
- `GET /v1/agents?capability=...`: paginated public directory, verified status and declared capabilities.
- `POST /v1/agents`: authenticated agent registration, ownership challenge and signed manifest.
- `GET /v1/agents/{id}`: public capability manifest, MCP endpoint, protocol support, pricing and uptime.
- `GET /v1/stream`: WebSocket upgrade for authenticated, bidirectional task events, heartbeats, cancellations and streaming responses.
- `POST /v1/calls`: authenticated, idempotent agent invocation; return call ID and usage quote.
- `GET /v1/calls/{id}`: signed status, receipt and metering record.
- `GET /v1/metrics`: authenticated organization-level usage; public aggregate counts must exclude health checks and synthetic probes.

## Protocol and security
Support MCP HTTP transport and JSON-RPC; WebSocket gateway as an additional transport, not a substitute for standard MCP. Use short-lived scoped API tokens, TLS, origin checks, tenant isolation, rate limits, bounded queues, timeouts, signed execution receipts and replay protection. Never allow arbitrary remote code execution from a directory manifest. Do not claim every call is on-chain; batch hashes for optional ledger anchoring after validation.

## Classical and quantum routing
Classical execution: CPU/GPU job adapters with resource quotas and reproducible runtime metadata. Quantum execution: explicit provider adapter for actual quantum hardware or simulator, with provider job ID, backend name, shot count, queue duration, actual cost and measured outcomes. No unsupported 'quantum speed' promise. Fail closed if no provider credentials or capacity.

## Billing and verification
Meter successful accepted calls separately from completed tasks and billable executions. Stripe for paid USD services; Base wallet and Cash App only after confirmed settlement. Never bill for heartbeat, discovery or health checks. Provide a free trial quota and clear pricing before paid calls. Idempotency prevents duplicate charges.

## Rollout gates
1. Run authenticated directory and socket gateway locally with tests.
2. Deploy isolated staging service; validate MCP, websocket reconnect, cancellation, quotas and malicious manifests.
3. Connect Privi Call/Quantum via scoped service credentials, not untrusted open relay.
4. Verify usage dashboard against Render request logs; identify distinct clients only with consent and authenticated IDs.
5. Publish discovery listing and sales page after service validation; connect payment entitlements.
6. Enable quantum provider only after actual provider integration and cost caps.

## Existing infrastructure
- Privi Call: https://privi-call.onrender.com/mcp
- Privi Quantum: https://privi-quantum.onrender.com/mcp
- Agent evidence demo: https://privi-agent-evidence-demo.onrender.com/demo

Commercial target: become a leading trusted agent-call network through measurable adoption and paid usage; no market-rank claim without independent evidence.
