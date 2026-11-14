# Privi Agent Survival & Premium — Worldwide MCP Directory Submission Pack

Updated: 2026-11-13. Maintainer: Privi World Corp.

## Canonical listing

- **Name:** Privi Agent Survival & Premium
- **Repository:** https://github.com/canoydario847-cloud/Privi-Network
- **Source and integration documentation:** https://github.com/canoydario847-cloud/Privi-Network/tree/main/privi-agent-survival
- **Remote Streamable HTTP MCP URL:** https://privi-ai-21-gateway.onrender.com/mcp
- **Official MCP Registry ID (maintainer-reported published v0.7.0):** `io.github.canoydario847-cloud/privi-agent-survival`
- **Website:** https://privi-ai-21-gateway.onrender.com/agent-hub
- **Categories:** Agent reliability, developer utilities, security, data quality, observability
- **Discoverability:** public initialize/tools-list; authenticated API key required to execute tools.
- **Count described by maintainer docs:** 32 standard utilities and 51 premium analyzers; do not interpret count as independently runtime-tested.
- **Billing clarification:** Automated prepaid API credits/Stripe/Base USDC checkout are not yet operational. Do not promise self-serve instant access.
- **Available separately:** human-delivered Guard Security Review ($99), Agent Evidence Review ($149), Enterprise Integration Consultation ($249) at https://privi-services.onrender.com/.

## Suggested directory description

Privi Agent Survival & Premium offers a remote MCP gateway with 32 agent reliability utilities and 51 premium analyzers covering authorization, data quality, error budgets, cost modeling, workflow readiness and security evidence. Clients can publicly discover tools; executing tools requires an authenticated prepaid credential. API-credit checkout is not yet available; three separate human-delivered B2B review and consulting services are available for purchase.

## Connector example

```json
{
  "mcpServers": {
    "privi-agent-survival": {
      "url": "https://privi-ai-21-gateway.onrender.com/mcp"
    }
  }
}
```

**Note:** Actual tool invocation requires a securely supplied API bearer token. Do not commit API keys.

## Directory queue

Status terminology: **maintainer-reported** means recorded in repository documentation but not independently confirmed in this campaign; **needs submission** means no directory acceptance is claimed. Do not change to published without a public listing URL.

| Directory | Submit / listing page | Status | Dependency |
|---|---|---|---|
| Official MCP Registry | https://registry.modelcontextprotocol.io/ | Maintainer-reported published v0.7.0 | Verify indexed listing and metadata |
| MCPServers.org | https://mcpservers.org/en/submit | Existing repo badge; listing needs recheck | Check published server page |
| Glama | https://glama.ai/ | Needs submission / claim | Sign-in or index from registry/GitHub |
| MCP.so | https://mcp.so/submit | Needs submission | Form and moderation |
| Cline MCP Marketplace | https://github.com/cline/mcp-marketplace/issues/new/choose | Needs submission | 400x400 PNG logo; tested setup docs; review |
| Smithery | https://smithery.ai/ | Needs eligibility check | November 2026 directory changes; verify current route |
| mcp.directory | https://mcp.directory/ | Needs submission | Site form or import |
| MCP Market | https://mcpmarket.com/submit | Needs submission | Site form |
| LobeHub MCP Marketplace | https://lobehub.com/mcp | Needs submission | Site-specific claim/CLI |
| cursor.directory | https://cursor.directory/ | Needs submission | Repo metadata / sign-in |
| GitHub MCP Registry | https://github.com/mcp | Needs eligibility check | Official registry first |
| PulseMCP | https://www.pulsemcp.com/ | Registry indexing / paused submissions reported | Do not claim direct submission |
| punkpeye awesome-mcp-servers | https://github.com/punkpeye/awesome-mcp-servers | Needs PR | Glama badge |
| awesome-remote-mcp-servers | https://github.com/punkpeye/awesome-remote-mcp-servers | Needs PR | Glama connector badge |
| ToolSDK MCP Registry | https://github.com/toolsdk-ai/awesome-mcp-servers | Needs submission-path verification | GitHub PR |
| Docker MCP Catalog | https://github.com/docker/mcp-registry | Eligibility conditional | Docker packaging |
| Kilo Marketplace | https://github.com/Kilo-Org/kilocode | Needs submission-path verification | GitHub PR |
| Gemini CLI Extensions | https://github.com/google-gemini/gemini-cli | Eligibility conditional | Extension packaging |
| Claude connectors directory | https://claude.ai/ | Eligibility conditional | OAuth and platform review |
| ChatGPT plugin directory | https://chatgpt.com/ | Eligibility conditional | Published plugin package and review |

## Submission process and guardrails

1. Confirm HTTPS, MCP initialize, tools/list and safe auth behavior against a live client. The public repository metadata alone is not a successful live uptime check.
2. Keep accurate payment claims: API prepaid checkout not operational and no confirmed MCP API revenue.
3. Submit one canonical listing to each directory where third-party submissions are allowed. Do not spam unrelated issues or discussion threads.
4. Save each submitted URL, date, review result, and visible public listing link.
5. For platforms requiring OAuth, logos, packages, or maintainer verification, complete those prerequisites before claiming availability.
6. Promote globally using language-neutral links; translate the listing text for relevant markets without manufacturing user counts or uptime.

## Verified external discovery results (2026-11-13 search)

These pages were found by public search and are already indexed. Their reported health-test dates are historical; **do not treat as live uptime checks**.

| Privi service | Glama public URL | Directory status at time of search |
|---|---|---|
| Privi Verify | https://glama.ai/mcp/connectors/io.github.canoydario847-cloud/privi-verify | Indexed; reported healthy, test 2026-10-21 |
| Privi Call | https://glama.ai/mcp/connectors/io.github.canoydario847-cloud/privi-call | Indexed; reported healthy, test 2026-10-31 |
| Privi Anchor | https://glama.ai/mcp/connectors/io.github.canoydario847-cloud/privi-anchor | Indexed; reported healthy, test 2026-10-21 |
| Privi Ledger | https://glama.ai/mcp/connectors/io.github.canoydario847-cloud/privi-ledger | Indexed; reported **unhealthy**, test 2026-10-21; needs current verification |
| Privi Agent Survival & Premium | https://glama.ai/mcp/connectors/io.github.canoydario847-cloud/privi-agent-survival | **Not verified**: do not count as indexed without a working page |

Additional third-party indexed page: https://mcprepository.com/canoydario847-cloud/privi-network (covers broader Privi Network; not proof of current availability).

### Current directory-policy corrections

- Glama distinguishes open-source GitHub MCP servers from **hosted remote connectors**. For this separately maintained gateway, use the *hosted endpoint* submission flow rather than implying this public metadata repository is the gateway's deployable source. See https://glama.ai/mcp/faq.
- PulseMCP's submission page remains paused according to October/November 2026 directory reports; official registry indexing is the appropriate route.
- Smithery announced the end of its hosted proxy/SDK/CLI on 2026-10-31. Treat direct listing availability as needing fresh verification; **do not propose deploying the gateway to discontinued Smithery hosting**.
- GitHub MCP Registry is curated and a listing in the official registry is not proof of appearing in GitHub's curated list.
- A GitHub submission to a third-party repo attempted through this integration returned **HTTP 403**. No successful external publication is claimed from that attempt.
- Attempts to fetch the Privi gateway health and server-card pages from the web retrieval environment failed; **current live service health is unverified**.

## Highest-priority remaining work

1. Validate public gateway health, MCP initialize and tools/list using an environment with permitted outbound connectivity. Resolve any defects first.
2. Submit **Privi Agent Survival & Premium** as a hosted *connector* at Glama, using the endpoint and truthful paid-checkout disclosure.
3. Claim/refresh already indexed Privi Verify, Call, Anchor and Ledger listings; investigate stale unhealthy Ledger status.
4. Submit canonical gateway info via free review options on mcp.so and mcpservers.org and retain confirmation IDs; do not pay for priority review.
5. Do not claim premium automated API usage is purchasable until durable billing/fulfillment is end-to-end verified.

## Infrastructure and gateway checks — 2026-11-13, subsequent repair pass

- **New Render workspace** `tea-dbr1aqjrjlhs73ccmcbg`: `privi-ai-21-gateway`, premium-tools site, services site, agent skills and Ledger recovery service were reported **not suspended**. Not suspended is not an uptime guarantee.
- **Old Render workspace** `tea-db83bk8n74is73dklo00`: many legacy Privi services were reported **suspended due to billing**. This includes original Call, Quantum, Hub and Devnet. A code redeploy alone cannot clear provider billing suspensions; do not use those as reliable fresh customer acquisition endpoints until account billing is addressed.
- **Live gateway evidence:** Render deployment `dep-dbrq0clbedkc73bev6hg` was reported live on 2026-11-13; logs included successful `POST /mcp` HTTP 200 and `GET /health` HTTP 200. This confirms recent HTTP traffic but not end-to-end tool execution for paying users.
- **Concrete compatibility fix committed:** the gateway's `HEAD /health` returned 404 while `GET /health` returned 200. Commit [792ae296cdac](https://github.com/canoydario847-cloud/Privi/commit/792ae296cdacfb532c6971ac0a1dd2a6fc1e8ad5) adds an HTTP 200 HEAD health response. Render auto-deploy `dep-dbrq2im417fc73epl8o0` started; deployment/runtime verification still pending at time this note was written.
- **Ledger recovery:** new-workspace `privi-ledger-mcp-recovery` deploy `dep-dbrq13ajnfac73bi9c30` was reported live, but MCP/health functionality on that recovery URL has not been independently validated. The existing Glama canonical Ledger connector still needs rechecking.
- **Third-party distribution:** no new directory approval in this repair pass; don't count GitHub issue creation as marketplace publication.


## Follow-up verification — 2026-11-13

- Render reports gateway deployment `dep-dbrq2im417fc73epl8o0` **live** after commit `792ae296cdac` (HEAD /health compatibility fix). Previous deployment was deactivated. This confirms deployment completion, **not independently a successful HEAD probe**.
- Render reports Ledger recovery deployment `dep-dbrq2qeq1p3s73e37gfg` **live** following the distribution documentation commit. Latest available Ledger recovery warning/error logs include a third-party `api.filepad.ai/mcp` HTTP 500 response, apparently from external registry scanning, not by itself proof that Privi Ledger's own MCP endpoint is broken.
- The direct external web retrieval environment could not fetch either gateway or recovery `/health` URL. Separate public GET /health 200 responses have appeared in gateway Render request logs; direct current checks remain incomplete.
- Do not mark Glama's stale unhealthy Ledger listing repaired without testing the canonical MCP connector and updating its registration endpoint if appropriate.

## Continued validation — 2026-11-13

- Privi gateway hotfix deployment `dep-dbrq2im417fc73epl8o0` confirmed **live** by Render.
- A third-party crawler identified itself as Neuronto and requested `GET /mcp`; Render logged HTTP 405. The server is an HTTP JSON-RPC POST implementation, and a GET 405 is an expected allowed transport response here, **not evidence of outage or a new marketplace listing**.
- Added regression test to `agent-gateway/server.test.js` for `HEAD /health` HTTP 200, empty response body, and unchanged `GET /health` status. Commit [af0a963](https://github.com/canoydario847-cloud/Privi/commit/af0a96319265d6f187b1b580e74ad6819490b6cb). Render auto-deploy `dep-dbrq3te417fc73epmji0` started; test execution on CI and HEAD response in production are not yet independently attested.
- Requests for direct HTTP checks from this environment could not resolve the remote hostname. Do not interpret these environment errors as service outages.

## Deployment follow-up — 2026-11-13

- The latest Privi agent gateway deploy `dep-dbrq3te417fc73epmji0` (commit `af0a96319265d6f187b1b580e74ad6819490b6cb`) is reported **live** by Render after successful startup, at 23:49:41 UTC. The previous HEAD-health compatibility build was already live before this deployment.
- On the gateway, Render logged HTTP 200 responses for `GET /health`, `GET /agent-hub`, `GET /agent-skills`, `GET /tools.json`, `GET /skills/index.json`, and multiple `POST /mcp` requests during a pre-deploy smoke test. These do not demonstrate paid purchase fulfillment or paid tool usage.
- Public URL fetches from the web retrieval environment for `/health`, Ledger recovery `/health`, and the server-card URL remained inaccessible in that environment, so **direct external HEAD /health, Ledger health and server-card checks remain unconfirmed**. Render's build command performs syntax checks but does not execute `npm test`; new regression test passing is not proven merely by a live deployment.

## CI gate improvement — 2026-11-13

- Found `Privi Agent Gateway Tests` GitHub Actions workflow only triggered on pushes to `agent-api-21-launch`, omitting production `main` branch push events.
- Fixed the workflow to trigger on `main` and `agent-api-21-launch` while retaining the existing `agent-gateway/**` and workflow file path filters. Commit [a36d9546](https://github.com/canoydario847-cloud/Privi/commit/a36d9546ca4af3dd8861763342f559537a5c5d3c).
- The workflow uses Node 22 and PostgreSQL 16 and runs `npm test` in `agent-gateway`. A prior code change added a `HEAD /health` regression test.
- GitHub combined commit status returned no statuses at time of verification. This does **not** show tests passed or failed. Check workflow run details separately before asserting green CI. GitHub workflow success alone does not gate Render auto-deployment unless Render is separately configured to wait for those checks.
- Render detected the workflow file commit and began auto-deploy `dep-dbrq69h5efls73e19mfg`; preceding gateway deployment `dep-dbrq3te417fc73epmji0` was live.

## Registry publication workflow repaired — 2026-11-13

- Found the repository's official MCP Registry GitHub Actions workflow [`.github/workflows/mcp-registry-publish.yml`](https://github.com/canoydario847-cloud/Privi-Network/blob/main/.github/workflows/mcp-registry-publish.yml) **did not include `privi-agent-survival`** in its push path filters or publish matrix, even though `privi-agent-survival/server.json` existed and its v0.7.0 was described as published.
- Fixed both workflow path filter and matrix to include `privi-agent-survival`; commit [b6321cc](https://github.com/canoydario847-cloud/Privi-Network/commit/b6321cc73cbcc09b57948e7cb7f9aadabaccc3f2).
- Updated metadata `privi-agent-survival/server.json` to v0.7.1, linking the Agent Hub as the website and explaining credential requirements and unfinished automated checkout; commit [bba431f](https://github.com/canoydario847-cloud/Privi-Network/commit/bba431ffbb58dfdac243461e07021842a8e02170).
- **Status: committed; publish triggered by matching GitHub push when Actions operates, but registry acceptance cannot be confirmed here.** Do not claim official v0.7.1 listed until an Actions publish success and registry lookup both verify it.
- Inspect [Registry publish workflow runs](https://github.com/canoydario847-cloud/Privi-Network/actions/workflows/mcp-registry-publish.yml) and look for the `privi-agent-survival` matrix job. Verify success before using v0.7.1 on external marketplace submissions.

## Merge review and registry API validation — 2026-11-13

- Queried open GitHub PRs for `canoydario847-cloud/Privi-Network` and `canoydario847-cloud/Privi`. Only open PR found: [#248](https://github.com/canoydario847-cloud/Privi-Network/pull/248), a **draft, non-mergeable** financial-mainnet provenance screening review. Its own stated criteria require independent review and monetary enforcement tests; it was **not merged**. No open MCP rollout PR required merging, because rollout patches are committed directly to `main`.
- Registry lookup workflow commit [701daf99](https://github.com/canoydario847-cloud/Privi-Network/commit/701daf99b41ba737549d2fea00957ea300e071de) now uses `/v0.1/servers/{serverName}/versions/{version}`, which is confirmed in the official [MCP Registry aggregator documentation](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/registry-aggregators.mdx). The registry's `/v0.1/` stable-version policy is also documented in [API changelog](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/api/CHANGELOG.md).
- GitHub reports two successful Railway deploy statuses for commit `701daf99` (not official Registry publish status). No proof that MCP Registry accepted `privi-agent-survival` v0.7.1 yet; do not count as newly listed until registry result is independently confirmed.
- The [official registry README](https://github.com/modelcontextprotocol/registry) says publishing to the registry itself must use `mcp-publisher`, not a pull request to its repository. The existing GitHub Actions workflow does use the publisher CLI with GitHub OIDC; inspect its run output next.
