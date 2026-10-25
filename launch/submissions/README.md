# Directory submissions

Files to send to directories that need a pull request or an issue. Each one is prepared here so the submission is copy and paste.

## Docker MCP Catalog

Shows Privi in Docker Desktop's MCP Toolkit and on hub.docker.com/mcp. Hosted servers need no Dockerfile.

1. Fork https://github.com/docker/mcp-registry on GitHub.
2. Copy `docker-mcp-registry/servers/privi-ledger/` and `docker-mcp-registry/servers/privi-verify/` into the fork's `servers/` folder.
3. Open one pull request per server (the Docker team prefers that). Title: `Add privi-ledger remote server` (and `Add privi-verify remote server`).
4. In the PR description, confirm: the URL is public, no OAuth is needed, and the docs link works.

Docker reviews every PR; approved servers appear within 24 hours.

## Cline MCP Marketplace

1. Open a new issue at https://github.com/cline/mcp-marketplace/issues/new.
2. Paste the text from `cline-marketplace-issue.md`.
3. Attach `assets/logo-400.png` (400×400 PNG) to the issue.

Approval usually takes about two days.

## x402 Bazaar (Coinbase)

No submission. Privi Verify and Privi Ledger already declare their paid tools to the Bazaar. A tool is indexed after its first real paid call settles through the Coinbase facilitator (up to 15 minutes later).
