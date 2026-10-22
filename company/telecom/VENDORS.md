# Privi Call carrier — vendors to build on

Prices change; agents look them up on the vendor's pricing page on the day and record the date.
Never create vendor accounts or buy anything — **STOP: Dario**.

| Need | Options to compare | In use |
|---|---|---|
| Numbers + voice + SMS (CPaaS) | Twilio, Telnyx, Bandwidth, Plivo, SignalWire | Twilio (phone line webhooks) |
| Wholesale SIP trunking (Phase 2+) | Telnyx, Bandwidth, Flowroute, Commio | — |
| STIR/SHAKEN signing (own certificate) | Signing-as-a-service vendors that sign with the provider's own SPC token; STI-PA registration | — |
| 911 for VoIP | Bandwidth 911, Intrado, RedSky | — |
| Speech in/out | Upstream provider's built-in speech; a TTS/STT vendor only if quality demands it | Twilio `<Gather>` + `<Say>` |
| Small LLM fallback | Anthropic API (`ANTHROPIC_API_KEY`, `CALL_LLM_MODEL`) | optional |
| CNAM / caller name | Upstream CNAM registration | — |
| Compliance help | Telecom attorney; 499/USAC filing services | — |

## Comparison checklist for each CPaaS

Per-number monthly price, per-minute inbound/outbound (US), SMS price + carrier fees, 10DLC fees,
sub-account support (one per Privi customer), number porting support, API for STIR/SHAKEN attestation,
911 address API, webhooks signature scheme, SLA, data residency, whether reselling is allowed in their terms.

Write findings to `company/telecom/research/cpaas-comparison-<date>.md` with links.
