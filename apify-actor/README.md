# Post-Quantum TLS Check (Apify Actor, by Privi)

Checks websites and APIs for **TLS 1.3** and **hybrid post-quantum key exchange** (X25519MLKEM768 / SecP256r1MLKEM768, NIST FIPS 203), the protection against "harvest now, decrypt later". One dataset row per host: status (`pq_hybrid`, `tls13_classical`, `tls12`, `no_tls13`), negotiated TLS version and group, and the next step. A `SUMMARY` record gives the share of hosts that are ready.

**Who it's for:** U.S. agencies and contractors preparing EO 14409 / OMB M-26-15 migration evidence, security teams building a cryptographic inventory (CBOM), and anyone auditing vendors.

**How it works:** two raw TLS ClientHellos per host. No handshake is completed and no application data is sent. Only public, globally routable addresses on TLS ports are probed.

**Pricing:** pay per event, `host-checked` (one charge per host that answered). Invalid, private or unreachable hosts are never charged.

Built by Privi World Co (Port Huron, Michigan). For signed readiness packages with the federal deadline per asset and a CycloneDX 1.6 CBOM, use the Privi Quantum MCP server: https://privi-quantum.onrender.com/mcp

## Publish (owner steps)
1. `npm i -g apify-cli && apify login`
2. From this folder: `apify push`
3. Apify Console → this Actor → **Publication**: make it public; **Monetization** → Pay per event → add event `host-checked` (suggested $0.002 per host).
