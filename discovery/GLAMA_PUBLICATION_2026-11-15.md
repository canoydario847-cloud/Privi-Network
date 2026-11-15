# Glama publication and connector refresh — 2026-11-15

**Publisher:** Privi World Corp · **Repository:** https://github.com/canoydario847-cloud/Privi-Network  
**Public Glama GitHub server:** https://glama.ai/mcp/servers/canoydario847-cloud/Privi-Network  
**Contact:** canoydario847@gmail.com

This is the canonical, copy-ready Glama submission pack for the **six distinct hosted MCP services**. These are not 83 separate server submissions: the Agent Survival gateway advertises 83 tools on one MCP endpoint. Do not duplicate existing Glama records or register websites, static landing pages, unpublished prototypes or a not-yet-launched financial mainnet as live MCP endpoints.

As of 2026-11-15, the connected Render workspace shows the five standalone MCP services below as deployed, with latest deploy status `live`; it also shows the gateway deployment `live`. **A Render deployment state does not prove an end-to-end Glama MCP handshake, billing, x402 settlement or user fulfillment.** Glama records below may still be using retired, unsuffixed Render domains; maintainers need to refresh existing Glama entries to the replacement addresses.

## Existing Glama listings → current MCP endpoints

| Product | Current MCP endpoint (submit/replace URL) | Existing Glama connector | GitHub metadata |
| --- | --- | --- | --- |
| **Privi Ledger** | `https://privi-ledger-aqe5.onrender.com/mcp` | [Privi Ledger](https://glama.ai/mcp/connectors/io.github.canoydario847-cloud/privi-ledger) | [ledger-server/server.json](../ledger-server/server.json) |
| **Privi Verify** | `https://privi-verify-s4jb.onrender.com/mcp` | [Privi Verify](https://glama.ai/mcp/connectors/io.github.canoydario847-cloud/privi-verify) | [mcp-server/server.json](../mcp-server/server.json) |
| **Privi Anchor** | `https://privi-anchor-zsbk.onrender.com/mcp` | [Privi Anchor](https://glama.ai/mcp/connectors/io.github.canoydario847-cloud/privi-anchor) | [anchor-server/server.json](../anchor-server/server.json) |
| **Privi Quantum** | `https://privi-quantum-vvmj.onrender.com/mcp` | [Privi Quantum](https://glama.ai/mcp/connectors/io.github.canoydario847-cloud/privi-quantum) | [quantum-server/server.json](../quantum-server/server.json) |
| **Privi Call** | `https://privi-call-e3rb.onrender.com/mcp` | [Privi Call](https://glama.ai/mcp/connectors/io.github.canoydario847-cloud/privi-call) | [call-server/server.json](../call-server/server.json) |
| **Privi Agent Survival & Premium** | `https://privi-ai-21-gateway.onrender.com/mcp` | [Agent Survival](https://glama.ai/mcp/connectors/io.github.canoydario847-cloud/privi-agent-survival) | [privi-agent-survival/server.json](../privi-agent-survival/server.json) |

All six declare remote `streamable-http` transport in their `server.json` files. The first five are hosted on the replacement Render workspace; the agent gateway retained its original working subdomain. No Glama approval is claimed for any new submission beyond the existing indexed listings.

## Descriptions for each separate Glama connector

Use these texts with **Add Server → Hosted endpoint** or when editing the **existing** connector.

| Name | Short description |
| --- | --- |
| Privi Ledger | AI-agent audit and security evaluation MCP. Check agent evidence, actions and receipts. Temporary recovery storage is not durable audit proof. |
| Privi Verify | Manufacturing lot and chain-of-custody verification tools over MCP, with x402 USDC payment integration on Base. |
| Privi Anchor | Hash proof-of-existence and verification over MCP. Base on-chain submissions are currently paused pending gas/payment readiness. |
| Privi Quantum | Quantum-related optimization, security readiness, agent inspection and research tools over remote MCP. |
| Privi Call | MCP agent-call directory and router: register agents, discover tools, route calls, and verify call records. |
| Privi Agent Survival & Premium | 83 discoverable agent tools: 32 basic utilities and 51 premium analyzers. Authenticated access; self-service API checkout not live. |

**Common metadata:** Language: English · Category: Developer Tools / Agent Orchestration / Security as appropriate · Repo: https://github.com/canoydario847-cloud/Privi-Network · Publisher: Privi World Corp · Contact: canoydario847@gmail.com.

## Honest capability, payment and deployment notes

- **Ledger:** Its latest official-registry metadata labels the deployment a *recovery evaluation* with temporary storage and payments disabled. Do not sell durable compliance proofs from that evaluation state.
- **Anchor:** Base transaction submission is paused while gas payment is unresolved; proof read/check functions may still be discoverable.
- **Agent Survival:** Tools are discoverable, but automatic prepaid API-key checkout/issuance has not passed live fulfillment verification. Do not advertise instant activation.
- **Commercial buyer offers:** Existing separate Stripe links advertise three human-delivered reviews at **$19.99 one time each** and **Privi Pro Unlimited at $35 one time**. These are **not** a working automated MCP-credit purchase. See [official Privi sales page](https://privi-services.onrender.com/); buyers must coordinate activation/fulfillment.
- **Native Privi financial mainnet:** Not launched. Do not describe Privi's own chain as an active financial mainnet.

## Glama quality and search-visibility gate (publisher dashboard)

Glama's published [indexing methodology](https://glama.ai/mcp/methodology) says approved GitHub MCP servers are built in an isolated environment and must pass reproducible build + MCP introspection checks before being distributed in search. Its [release instructions](https://glama.ai/blog/2026-03-15-how-to-make-a-release) require a separate Glama build/release, **not merely a GitHub tag/release**.

1. Open [Privi Network → Dockerfile](https://glama.ai/mcp/servers/canoydario847-cloud/Privi-Network/admin/dockerfile) while logged in as the authorized Glama publisher. The repo is a **monorepo**, not a single Python application; Glama must select a runnable subfolder explicitly.
2. A simple buildable representative choice is the public **Privi Verify** application in `mcp-server/`, which already provides an installable `pyproject.toml` and a `--stdio` CLI. Suggested builder inputs (not an independently tested Glama deployment):
   - Python: **3.13**
   - Install/build step from repository root: `python -m pip install --no-cache-dir ./mcp-server`
   - Command / CMD (stdio mode): `privi-verify-mcp --stdio`
   - Temporary database: `PRIVI_DB_PATH=/tmp/privi-glama-inspect.db`
   - Never supply production private keys, Stripe credentials, or signing secrets to a public build.
   - **Important:** Privi Verify's `Settings.validate()` requires a valid `PRIVI_PAY_TO` address if payments are enabled. Do not set `PRIVI_PAYMENTS_ENABLED=0` to make a public release pass: that would risk free execution of paid tools. Production-ready payment settings and a fail-closed inspection profile must be confirmed before publishing a deployable release. This example alone is *not a ready-to-publish production configuration*.
3. Click **Deploy** in the Glama dashboard to run the builder/inspection. Inspect the build logs and verify `initialize`, `tools/list`, plus any resources/prompts discovery. Address failures without bypassing paid execution/authentication.
4. After passing the check, use **Make Release → Create & Publish Release** on Glama, if the intended deployed service and its public listing description agree. Running only Verify does **not** expose the other five Privi endpoints automatically. Avoid implying a Verify-only image is a full Privi Network execution gateway.
5. Recheck [Discovery score](https://glama.ai/mcp/servers/canoydario847-cloud/Privi-Network/admin/score), published search visibility, tool definitions, and category metadata. Do not claim the score improved until Glama reports a new result.
6. For *hosted connectors*, use the existing connector **Admin → Test Profile → Test Connection**, then confirm healthy `initialize`/tool discovery. A passing source build does not automatically repair a stale **remote connector URL**.

Publisher note: GitHub's `glama.json` currently has the documented schema + maintainer identity; it does **not** configure the separate Glama build/release dashboard. Do not submit duplicate server records in an attempt to raise a score.

## Publisher action checklist

1. Sign into [Glama's connectors directory](https://glama.ai/mcp/connectors) and locate the **existing** Privi entry for each product (links above).
2. In each existing connector's **Admin** page, replace any `https://privi-<name>.onrender.com/mcp` legacy host with the exact current endpoint in the table. Save and request reinspection; do **not** add a duplicate record. The Agent Survival endpoint has not changed.
3. Confirm Glama Inspector can `initialize` and `tools/list` on each new URL. Anonymous tool discovery may be permitted while `tools/call` requires authorized payment; use a dedicated least-privilege test profile for paid operations.
4. In the [Privi Network GitHub server admin](https://glama.ai/mcp/servers/canoydario847-cloud/Privi-Network/admin/repository), click **Sync Server** to refresh metadata after repo changes; review the public [Discovery score](https://glama.ai/mcp/servers/canoydario847-cloud/Privi-Network/admin/score).
5. If Glama cannot edit existing connector URLs, [contact Glama support](https://glama.ai/support) with the six-row mapping above, asking for a *URL replacement and reinspection* rather than duplicate listings.
6. Monitor Glama analytics for actual visits/installs. Confirm revenue only against verified Stripe or Base payment records, not tool discovery counts.

**2026-11-15 observation:** The public Glama **Privi Network** GitHub server is approved/listed. The publisher's Glama admin showed a 25% discovery score. Several old connector pages were last inspected before the Render migration and may have stale health statuses.

---
This document is publisher guidance and does not itself submit Glama forms or change remote Glama account settings.
