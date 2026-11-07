# Privi Quantum-Safe Check (GitHub Action)

Find the cryptography a quantum computer breaks: RSA, elliptic curves, Diffie-Hellman, DSA, plus
committed private keys and classically broken hashes. You get a **quantum readiness score (0-100)**,
a fix for every finding, a job summary, a README badge, and SARIF for GitHub's Security tab.

Free. It runs entirely in your CI: no account, no API key, and no code leaves the runner.

```yaml
# .github/workflows/quantum-safe.yml
name: Quantum-safe check
on: [push, pull_request]
permissions:
  contents: read
  security-events: write   # only needed for the SARIF upload step
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: privi
        uses: canoydario847-cloud/Privi-Network/actions/quantum-safe@main
        with:
          fail-on: critical      # critical | high | medium | none
      - uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: privi-quantum.sarif
```

| Input | Default | What it does |
|---|---|---|
| `path` | `.` | File or folder to scan |
| `fail-on` | `critical` | Fail the job at this severity or worse (`critical`, `high`, `medium`, `none`) |
| `sarif-file` | `privi-quantum.sarif` | SARIF output path (empty to skip) |
| `show-info` | `false` | Also list post-quantum crypto already in use |

Outputs: `score`, `critical`, `high`, `sarif-file`.

The scan is pattern-based: it shows you where to look. A clean result means nothing obvious was found,
not that the code is proven quantum-safe. For signed post-quantum readiness packages (EO 14409 /
OMB M-26-15), live TLS endpoint checks and quantum-safe agent identity, use
[Privi Quantum](https://privi-quantum.onrender.com).

Same scanner as the Privi Quantum MCP server (`quantum-server/src/privi_quantum/scanner.py`).
Copyright (c) 2026 Privi World Co.
