# Privi Ledger MCP Server

Privi Ledger gives AI agents a trust layer: it checks what an agent reads and sends, records what it did, and proves it later.

## Features

- **Privi Guard**: check untrusted text (web pages, emails, tool output) for prompt injection before an agent acts on it. Returns a verdict, a risk score and a signed receipt.
- **Audit logs**: hash-chained, tamper-evident logs of an agent's actions, with checkpoints anchored on Base.
- **Passports and KYA**: signed trust credentials for agents, and wallet-to-agent binding, that anyone can verify for free.
- **Compliance reports**: sealed reports and PDFs auditors can verify.

## Pricing

Most tools are free and need no key. A free organization key (`ledger_signup`) adds audit logs and a monthly Guard allowance. Paid calls use x402 and settle in USDC on Base; `guard_pricing` lists the prices.

## More information

See the [Privi Ledger docs](https://github.com/canoydario847-cloud/Privi-Network/tree/main/ledger-server).
