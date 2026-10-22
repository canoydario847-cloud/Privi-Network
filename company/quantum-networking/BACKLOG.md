# Privi Quantum Network — backlog

**STOP: Dario** = prepare, list in the PR under "Needs Dario", stop.

## Phase 0 — quantum-safe now

- [ ] Q1. Audit every Privi service with `pqc_scan_code` (quantum-server) and file the results in `research/pqc-audit-<date>.md`.
- [ ] Q2. Turn on hybrid PQC TLS where Privi controls TLS (outbound calls from call-server to agents; custom domains via Render — check what Render's edge supports and document it).
- [ ] Q3. Shared `privi_pqc` module (ML-DSA-87 sign/verify, ML-KEM-1024 encapsulate) extracted from quantum-server, used by call-server records (telecom T5).

## Phase 1 — Privi Key Manager

- [ ] Q4. New `quantum-net/` service skeleton (layout in ARCHITECTURE.md), added to `render.yaml` with a disk.
- [ ] Q5. BB84 simulator exposing ETSI GS QKD 014 endpoints, with configurable distance, loss and eavesdropper (QBER rises when Eve is on).
- [ ] Q6. KMS: sources (PQC, ETSI 014, simulator), KDF combine, rotation, sealed key-event log anchored every 5 minutes.
- [ ] Q7. MCP tools `qnet_status`, `qnet_link_create`, `qnet_key_get`, `qnet_verify_log`, `qnet_readiness`; landing page with live link stats; discovery files; `server.json`.
- [ ] Q8. Quantum-secured Privi-to-Privi calls: SRTP keys from the KMS; badge on call records.
- [ ] Q9. Site `sites/quantum-network/` on priviflow.us explaining the honest limits and the roadmap.

## Phase 2 — QKD pilot

- [ ] Q10. Outreach drafts to Chicago Quantum Exchange partner program, Quantum Corridor, Qunnect ABQ-Net. **STOP: Dario** to send.
- [ ] Q11. Test plan for a real ETSI 014 device/partner link (what to measure, acceptance numbers).
- [ ] Q12. SBIR/STTR quantum-network section drafts. **STOP: Dario** to submit.

## Phase 3 — later

- [ ] Entanglement-based services on a partner network.
- [ ] Quantum-secured trunks between Privi Call sites.
