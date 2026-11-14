# Privi remote MCP — free catalog submission package
Date: 2026-11-14

## Official registry (already listed)
- io.github.canoydario847-cloud/privi-agent-survival v0.7.1
- https://registry.modelcontextprotocol.io/v0.1/servers/io.github.canoydario847-cloud%2Fprivi-agent-survival/versions/0.7.1

## Submission blocked by upstream permissions
Connected GitHub integration has read-only access to external repositories; no fork creation or external write permissions. An attempt to open a TensorBlock/awesome-mcp-servers issue failed with HTTP 403 ("Resource not accessible by integration"). Do **not** report external listings or PRs as published.

### Kilo Marketplace
- https://github.com/Kilo-Org/kilo-marketplace
- Copy [MCP.yaml](kilo-marketplace/MCP.yaml) into a fork at mcps/privi-agent-survival/MCP.yaml, run required validation, open PR to upstream main.
- This is a *prepared submission*, not an accepted marketplace listing.

### TensorBlock MCP Index
- https://github.com/TensorBlock/awesome-mcp-servers
- Submit via the repository's Add MCP Server issue form or add in the appropriate docs/*.md category in a fork.
- Hosted endpoint: https://privi-ai-21-gateway.onrender.com/mcp
- Listing source: https://github.com/canoydario847-cloud/Privi-Network/tree/main/privi-agent-survival

### ToolSDK MCP Registry
- https://github.com/toolsdk-ai/toolsdk-mcp-registry
- Fork and add a JSON file under packages/uncategorized, following the current schema. This project may expect a package/runtime rather than purely hosted private-source MCP: verify compatibility before PR.

### Docker MCP Registry
- https://github.com/docker/mcp-registry/blob/main/CONTRIBUTING.md
- Remote hosted servers are explicitly supported; their workflow uses remote-wizard, remote metadata, endpoint and possibly auth test credentials. Validate before a PR; no credentials should be committed.

### ToolHive
- https://github.com/stacklok/toolhive-registry
- Requires open-source, quality/security criteria; Privi's hosted proprietary implementation may not qualify. Don't publish misleading source/license claims.

### GitHub MCP Registry
- https://github.com/mcp is a discovery organization page, not an open PR listing repository. The official registry is already published; no second duplicate submission.

### Gemini CLI Extensions
- https://github.com/google-gemini/gemini-cli
- Requires a compatible distributable extension and installation manifest; direct directory listing of a remote URL is not established.

### International / AIBase
- The supplied LobeHub link does not identify a dedicated "AIBase" submission endpoint. Locate and verify a real catalog before any claim of submission.

## Listing facts
- Name: Privi Agent Survival & Premium
- Endpoint: https://privi-ai-21-gateway.onrender.com/mcp
- Transport: streamable-http
- Auth: Bearer API key for tool execution; discovery public
- 32 standard plus 51 premium deterministic analyzers
- Automated API-credit payment/fulfillment: not yet operational
- No OAuth 2.1 / DCR claim; no verified active paying users inferred from listing
- Maintain accurate documentation and avoid sharing private signing keys, Stripe secrets or other credentials.
