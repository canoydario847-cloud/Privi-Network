# Privi apps

One app per product. Each is an installable web app served by that product's own server at `/app/`, plus a Google
Play project (a Trusted Web Activity that opens the same page full screen).

| App | Web app | Android package | Android project |
|---|---|---|---|
| Privi Ledger | https://privi-ledger.onrender.com/app/ | `us.priviflow.ledger` | `android-ledger/` |
| Privi Quantum | https://privi-quantum.onrender.com/app/ | `us.priviflow.quantum` | `android-quantum/` |
| Privi ChainFlow | https://privi-verify.onrender.com/app/ | `us.priviflow.chainflow` | `android-chainflow/` |
| Privi Anchor | https://privi-anchor.onrender.com/app/ | `us.priviflow.anchor` | `android-anchor/` |
| Privi Call | https://privi-call.onrender.com/app/ | `us.priviflow.call` | `android-call/` |

## How it works

- `app.html` is one page shared by all five. It asks the server for its tool list and builds a form for each tool
  from the tool's own description, so a new tool shows up in the app without any app change.
- Every action is an ordinary MCP tool call to the same server's `/mcp`. The app adds no new way in: the same keys,
  prices and paywall apply. A customer's key is kept in their browser only.
- Fields that take a document fingerprint have a "Fingerprint a file" button. The file is hashed on the device
  (SHA-256) and never uploaded.
- When a call needs payment, the app offers to pay with a browser wallet (x402, USDC on Base), the same flow as
  the existing `/pay` page. In a browser with no wallet it offers an "Open in MetaMask" link.

## Changing the apps

Edit `apps.json` (names, features, which tools each screen shows), `app.html` or `webapp.py`, then run

    python3 apps/build.py

which rewrites each server's `webapp.py` and `webapp/` folder, the five `android-*/` projects and their GitHub
workflows. Each server has `tests/test_webapp.py`, which fails if `apps.json` names a tool the server lacks.

## Releasing on Google Play

Each `android-*/README.md` has the steps and a suggested store listing. In short: run the workflow, upload the
`.aab` in Play Console, then set the app's signing fingerprint in Render (`LEDGER_ANDROID_SHA256`,
`QUANTUM_ANDROID_SHA256`, `CHAINFLOW_ANDROID_SHA256`, `ANCHOR_ANDROID_SHA256`, `CALL_ANDROID_SHA256`) so the app
opens without a browser bar.
