# Privi Quantum Network — playbook

**Goal:** make Privi the company that carries agent and phone traffic safely through the quantum era —
quantum-safe links today with post-quantum cryptography, quantum key distribution (QKD) where fiber
partners offer it, and entanglement-based services as the hardware matures.

## Honest starting point

- Privi does not own quantum hardware or fiber. Real QKD and entanglement need partner networks and hardware.
- What Privi already has: ML-DSA-87 signed attestations, a PQC code scanner and a QAOA service
  (`quantum-server/`), the Quantum-Ready government inventory in `ledger-server/`, and a sealed log anchored on chain.
- The US security agencies currently favor post-quantum cryptography over QKD for protecting systems,
  because QKD needs special hardware, trusted relay nodes over distance, and cannot authenticate on its own.
  So: **PQC first everywhere, QKD as an extra layer for customers who want it.**
- Commercial QKD on live US carrier fiber now exists in the Midwest: Quantum Corridor and Toshiba ran QKD
  across a 21.8 km Chicago–Hammond commercial link (Dec 2025). Qunnect opened ABQ-Net, an open-access
  entanglement testbed in Albuquerque (June 2026). These are the kinds of partners Privi plugs into.

## Files

| File | What it is for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Layers: PQC transport, key management, QKD adapters, entanglement services, sealed key log |
| [STANDARDS.md](STANDARDS.md) | NIST PQC, ETSI QKD key-delivery API, ITU-T, IETF hybrid TLS — what to implement |
| [PARTNERS_AND_FUNDING.md](PARTNERS_AND_FUNDING.md) | Testbeds, fiber partners, grants |
| [BACKLOG.md](BACKLOG.md) | Ordered tasks for agents, with **STOP: Dario** points |

## Phases

| Phase | Ships | Needs |
|---|---|---|
| **0. Quantum-safe now** | Hybrid PQC (ML-KEM + X25519) on all Privi services and calls; ML-DSA signatures on records | Software only |
| **1. Privi Key Manager** | A key management service that speaks the ETSI QKD key-delivery API, so QKD keys from any vendor (or a simulator) feed Privi links; every key event sealed and anchored | Software + simulator |
| **2. QKD pilot** | One real QKD-secured link via a testbed or carrier partner (Chicago/Midwest first) | Partner agreement, equipment access — STOP: Dario |
| **3. Quantum network services** | Entanglement distribution / time sync / quantum-secured trunks for Privi Call, sold per link | Partner network or own nodes |
