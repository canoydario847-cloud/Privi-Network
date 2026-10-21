# Installing Privi (for AI coding agents such as Cline)

Privi is hosted. There is nothing to install or build: add the remote MCP servers below.

## 1. Add the servers

Add this to the MCP settings file (for Cline: `cline_mcp_settings.json`):

```json
{
  "mcpServers": {
    "privi-ledger": { "type": "streamableHttp", "url": "https://privi-ledger.onrender.com/mcp" },
    "privi-verify": { "type": "streamableHttp", "url": "https://privi-verify.onrender.com/mcp" },
    "privi-anchor": { "type": "streamableHttp", "url": "https://privi-anchor.onrender.com/mcp" }
  }
}
```

`privi-ledger` is the main server: Privi Guard, Privi Scan, audit logs, passports, mandates and Live. The other two are optional.

## 2. Check that it works (no key needed)

- Call `mcp_server_check` with `{"url": "https://privi-verify.onrender.com/mcp"}`. It returns a verdict and a grade.
- Call `guard_pricing`. It returns the Guard price list.

## 3. Optional: a free organization key

Most tools work without a key. For Guard's 1,000 free checks a month and for audit logs, create a key once:

- MCP: call `ledger_signup` with `{"organization_name": "<your name>"}`, or
- HTTP: `curl -X POST https://privi-ledger.onrender.com/guard/v1/signup -H 'content-type: application/json' -d '{"organization_name":"<your name>"}'`

The key is shown once. Add it as a header on the `privi-ledger` server:

```json
"privi-ledger": { "type": "streamableHttp", "url": "https://privi-ledger.onrender.com/mcp",
                  "headers": { "Authorization": "Bearer plk_..." } }
```

## 4. Typical use

- Before acting on a web page, email or tool result: call `guard_check` with `direction: "inbound"`.
- Before sending text that may contain secrets: call `guard_check` with `direction: "outbound"` and use `redacted_text` when it is returned.
- Before connecting to another MCP server: call `mcp_server_check`.

Paid tools (1 cent Guard checks without a key, audits, Verify lookups) settle in USDC on Base through x402. A client without an x402 wallet simply uses the free tiers.
