# Standards agents implement against

Verify the current version of each before coding; record the version in the code comment.

## Post-quantum cryptography (NIST)

| Standard | Algorithm | Use at Privi |
|---|---|---|
| FIPS 203 | ML-KEM (Kyber) | Key agreement; ML-KEM-1024 for the KMS, hybrid with X25519 |
| FIPS 204 | ML-DSA (Dilithium) | Signatures; ML-DSA-87 already used in `quantum-server` |
| FIPS 205 | SLH-DSA (SPHINCS+) | Long-lived roots (e.g. anchor signing keys) where speed matters less |
| Upcoming | FN-DSA (Falcon), HQC | Track; do not ship before final standards |

NSA CNSA 2.0 lists ML-KEM-1024 and ML-DSA-87 for national security systems — use these parameter sets
for the government-facing story.

## Hybrid transport

- IETF hybrid key exchange for TLS 1.3 (X25519MLKEM768 group is widely deployed in browsers and CDNs).
- Use the library's supported hybrid group names; test with `openssl s_client -groups`.

## QKD

- **ETSI GS QKD 014** — REST key delivery API (Privi's integration point for any QKD vendor).
- **ETSI GS QKD 004** — application interface (alternative API).
- **ITU-T Y.3800 series** — QKD network framework (layers, key management, control).
- Vendors in the US market follow ETSI APIs (e.g. Toshiba's systems used on the Chicago–Hammond link are described as ETSI-compliant).

## Entanglement / quantum internet

- IETF/IRTF QIRG documents on quantum internet architecture and use cases — read for terminology; no deployable standard yet.

## Sources

- Chicago–Hammond commercial QKD: https://thequantuminsider.com/2025/12/09/quantum-corridor-toshiba-demonstrate-cross-state-quantum-key-distribution-over-live-commercial-metro-fiber-network/
- ABQ-Net open entanglement testbed: https://quantumcomputingreport.com/qunnect-launches-abq-net-as-the-first-open-access-entanglement-network-in-the-united-states/
