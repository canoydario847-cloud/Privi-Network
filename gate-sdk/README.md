# Privi Gate

**Let only AI agents with a valid Privi Passport call your API or MCP server.**

Every agent that wants to call a gated server needs a Privi Passport. That's a signed, on-chain-anchored
trust credential built from the agent's tamper-evident Privi Ledger history. Unknown, tampered, revoked or
low-trust agents are stopped at the door. Each one gets a 401 that explains exactly how to get a passport.

- **Zero dependencies.** Python (ASGI: FastMCP streamable HTTP, Starlette, FastAPI) and JavaScript (Express/Connect).
- **Your traffic stays yours.** Only the passport ID is checked with Privi Ledger, and answers are cached 5 minutes.
- **Monitor mode** labels callers without blocking anyone, so you can see who would be stopped before you enforce.
- **Free** for servers. Checks call Ledger's public `/passports/<id>` endpoint, which needs no key.

## Python

```python
from privi_gate import PriviGate

app = PriviGate(app, min_score=550)          # enforce (default)
# app = PriviGate(app, mode="monitor")       # watch first, block later
```

For a FastMCP server: `app = PriviGate(mcp.streamable_http_app(), min_score=550)`, then serve `app` with uvicorn.
Inside your handlers, `request.scope["state"]["privi_passport"]` has the decision (score, grade, reasons).

Not ASGI? `from privi_gate import check_passport; check_passport("pp_...").allow`

## JavaScript

```js
import express from "express";
import { priviGate } from "privi-gate";

const app = express();
app.use(priviGate({ minScore: 550 }));        // req.priviPassport has the decision
```

## Options

| Python / JS | Default | Meaning |
|---|---|---|
| `min_score` / `minScore` | 550 | Minimum live passport score (0-1000) |
| `min_grade` / `minGrade` | none | Minimum grade A-E, as an alternative |
| `mode` | `enforce` | `monitor` lets everyone through and only labels them |
| `exempt` | `/health`, `/.well-known/`, `/robots.txt` | Path prefixes that skip the check |
| `on_unreachable` / `onUnreachable` | `deny` | What to do if Privi Ledger can't be reached (`allow` to fail open) |
| `cache_seconds` / `cacheSeconds` | 300 | How long a decision is reused |
| `on_decision` / `onDecision` | none | Callback for logging every decision |

## What a passport check covers

Privi's signature, content unaltered since it was issued, not expired or revoked, the agent's audit history
still verifying (tampering after issue is caught), and its **live** score right now.

## For agents: getting a passport

1. `ledger_signup` (free) at `https://privi-ledger.onrender.com/mcp`
2. Record your actions with `ledger_record`. That history is what your passport scores.
3. `passport_issue`: free on Pro, $1 USDC via x402 on the free plan. Valid 30 days.
4. Send `X-Privi-Passport: pp_...` (or `Authorization: PriviPassport pp_...`) on every request.

Copyright (c) 2026 Privi World Co.
