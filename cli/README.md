# privi command-line tool

Use your live Privi Ledger from any Linux, macOS or Chromebook terminal. Python 3.9+ only; no packages needed
(except `cryptography` for `privi check-bundle`, which verifies evidence offline).

```
git clone https://github.com/canoydario847-cloud/Privi-Network.git   # or: git pull
mkdir -p ~/.local/bin && ln -sf ~/Privi-Network/cli/privi.py ~/.local/bin/privi
privi login        # paste your organization API key (hidden); saved to ~/.config/privi/config.json (mode 600)
privi status
```

Commands: `status`, `record STREAM TYPE "SUMMARY"`, `log STREAM`, `receipt HASH`, `report`, `pdf REPORT_ID`,
`passport [STREAM]`, `kya ADDRESS`, `bundle STREAM`, `check-bundle FILE`, `tree`, `stats`. Run `privi -h` for details.

Defaults to https://privi-ledger.onrender.com; set `PRIVI_LEDGER_URL` (or `privi login --url`) for another Ledger.
