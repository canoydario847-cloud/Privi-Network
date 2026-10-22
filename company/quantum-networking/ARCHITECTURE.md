# Privi Quantum Network — architecture

```
 Layer 4  Services        quantum-secured agent calls · quantum-secured phone trunks · key-as-a-service
 Layer 3  Trust           sealed key-event log (hash chain) ─► Privi Anchor ─► Base / Privi chain
                          ML-DSA-87 signed attestations per link session
 Layer 2  Key management  Privi Key Manager (KMS)
                          ├─ PQC source: ML-KEM-1024 + X25519 hybrid key agreement
                          ├─ QKD source: ETSI GS QKD 014 REST key delivery (vendor devices / partner)
                          └─ Simulator source: BB84 / decoy-state simulator for tests and demos
                          keys combined with a KDF so a link is safe if ANY source is safe
 Layer 1  Transport       TLS 1.3 with hybrid PQC groups · WireGuard-style tunnels with PQC pre-shared keys
                          · SRTP for voice keyed from Layer 2
 Layer 0  Physical        partner fiber / testbeds (QKD, entanglement) · ordinary internet for PQC
```

## Design rules

1. **Defense in depth:** a link key = KDF(PQC secret ‖ QKD key if present). Never QKD alone.
2. **Authentication is PQC:** ML-DSA-87 (and Ed25519 during transition) identifies endpoints, because QKD needs
   an authenticated classical channel.
3. **Every key event is sealed** (request, delivery, rotation, failure) — never the key material itself,
   only its SHA-256 commitment and metadata.
4. **Vendor-neutral:** QKD devices plug in behind the ETSI key-delivery API; no vendor SDK in core code.
5. **Measure and publish:** key rate, QBER (from simulator or device stats), uptime per link on a public status page.

## Code layout to create

```
quantum-net/                  (new service, Render web service with disk)
  src/privi_qnet/
    kms.py          key store, KDF combine, rotation
    sources/pqc.py  ML-KEM hybrid (reuse liboqs / existing quantum-server deps)
    sources/etsi014.py  client for ETSI GS QKD 014 (GET /api/v1/keys/{SAE_ID}/enc_keys, dec_keys, status)
    sources/sim.py  BB84 simulator exposing the same ETSI 014 API (lets everything be tested with no hardware)
    seal.py         hash-chained key-event log + Anchor checkpoints (copy call-server pattern)
    server.py       FastMCP: qnet_status, qnet_link_create, qnet_key_get, qnet_verify_log, qnet_readiness
  tests/
```

## Tie-in with Privi Call

- Voice: SRTP master keys for Privi-to-Privi calls drawn from the KMS → "quantum-secured call" badge on the call record.
- Agent calls: `call_agent` over hybrid-PQC TLS to Privi agents; call records signed with ML-DSA-87.
- STIR/SHAKEN uses ES256 (elliptic curve, quantum-vulnerable); Privi adds an ML-DSA-signed attestation
  of caller identity in the sealed log as a forward-looking proof (not a replacement for STIR/SHAKEN).
