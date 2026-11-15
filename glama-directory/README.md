# Privi Network — Glama source build

This directory contains the **catalog-only** MCP entrypoint for Glama's public *Privi Network* GitHub-server listing. It exists so Glama can reproducibly build and introspect a coherent server from the **root of this monorepo**.

It deliberately **does not proxy** or execute commercial Privi services. Those services continue to be deployed separately over remote Streamable HTTP, and each retains its own payment and authentication requirements. Only public metadata from [catalog.json](catalog.json) is exposed; all descriptions must be kept truthful when service availability changes.

## Glama administrator build configuration

- GitHub source: \`canoydario847-cloud/Privi-Network\` (default branch \`main\`)
- Repository-root \`Dockerfile\`: **present**; it copies only this directory and uses a non-root UID.
- Build test: the Dockerfile runs the included offline unit tests and Python compilation; **no production credentials, payment, wallet, or network access are required**.
- STDIO CMD arguments if the Glama admin form asks for them explicitly: \`["python","-u","/app/glama-directory/server.py"]\`
- Environment schema: \`{"type":"object","properties":{},"additionalProperties":false}\`
- Placeholder parameters: \`{}\`
- Glama admin: https://glama.ai/mcp/servers/canoydario847-cloud/Privi-Network/admin/dockerfile

After syncing source to the current \`main\` commit, build with **Deploy** in the Glama admin, verify introspection, and **Create & Publish Release**. These are Glama-side actions, not GitHub release/tag operations. Do not claim the listing is indexed, security-cleared, or A-scored until Glama reports success.

## Locally verify the protocol

\`\`\`bash
python3 -m unittest discover -s glama-directory -p 'test_*.py' -v
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check","version":"1"}}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | python3 -u glama-directory/server.py
docker build -t privi-glama-directory:local .
docker run --rm -i privi-glama-directory:local
\`\`\`

The catalog provides only two informational MCP tools:

- \`privi_network_service_directory\`: return six current MCP endpoints, feature summaries and Glama connector listings.
- \`privi_network_access_information\`: explain commercial access and human-delivered offer pricing.

These **do not issue keys or grant paid tool execution**. Other \`tools/call\` names are rejected. No third-party tokens are embedded, no privileged filesystem access is needed, and no outbound network calls are made. A production paid-service integration must continue to use its respective hosted endpoint; do not mistake this inspection image for production billing or mainnet infrastructure.

## Health and release boundaries

Existing Glama *hosted connector* entries are independent from this GitHub server. To repair their endpoint URLs or status, open each connector's **Admin → Test Profile** and retest the actual current remote endpoint; building this Dockerfile will not silently update those connector records.

Catalog source and updated remote endpoints: [Glama publication runbook](../discovery/GLAMA_PUBLICATION_2026-11-15.md).
