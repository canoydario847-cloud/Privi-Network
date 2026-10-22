# Privi Call carrier — target architecture

```
        callers (PSTN)            AI agents (MCP / A2A)           businesses (dashboard, API)
              │                           │                                 │
     upstream carrier SIP          call-server /mcp                  priviflow.us/call
     (Twilio / Telnyx / Bandwidth)       │                                 │
              │                           ▼                                 ▼
              └──────────────► Privi Call core (call-server) ◄──────── Numbers API
                                  │      │       │       │
                    voice agent ◄─┘      │       │       └─► Billing (x402 USDC, prepaid credits)
               (script + small LLM,      │       │
                speech in / out)         │       └─► Trust: Passport / KYA / Mandates (ledger-server)
                                         ▼
                              Sealed call log (hash chain, SQLite on Render disk)
                                         │ every 5 min
                                         ▼
                              Privi Anchor ──► Base (later: Privi chain)
```

## Components to build, in order

1. **Numbers service** (`call-server/src/privi_call/numbers.py`)
   - Search, buy, release and list numbers through the upstream provider API, one provider adapter per vendor
     (`providers/twilio.py`, `providers/telnyx.py`) behind one interface: `search(area_code)`, `buy(e164)`,
     `release(e164)`, `configure(e164, voice_url, sms_url)`.
   - Each Privi number belongs to an owner: a Privi org (Ledger org key) or an agent Passport.
   - MCP tools: `number_search`, `number_buy` (x402, monthly), `number_list`, `number_release`, `number_route`
     (send calls to: an MCP agent, a voice agent script, a forward number, voicemail).
   - Purchases happen only when billing is open (CDP keys set) and only in Privi's upstream account.
2. **Routing per number** — a `routes` table: number → target (agent number on the Privi Call network,
   forward E.164, voice-agent profile, voicemail). `/voice/inbound` looks up the dialled number.
3. **Voice agent profiles** — per-number greeting, knowledge, hand-off rules, business hours. Script first
   (no per-call AI cost); a small model only for questions the script misses, capped per call.
4. **Outbound calls by agents** — `call_dial(to, from_number, purpose)` allowed only when:
   the caller holds a Passport above a threshold, a valid Mandate covers the spend, the destination is not
   on the do-not-call list Privi keeps, and the time is within calling hours for the destination's time zone.
   Every attempt is logged, including refusals. This is the robocall-mitigation story — see REGULATORY.md.
5. **SMS** — inbound/outbound on Privi numbers; US A2P 10DLC brand and campaign registration is required
   before business texting (STOP: Dario for registration).
6. **Call proof** — each call record gets an ML-DSA-87 signature (reuse `quantum-server/src/privi_quantum/attest.py`)
   so the proof outlives quantum computers; public `/calls/<id>` shows hashes, signature, anchor.
7. **Customer dashboard** — `sites/call/`: numbers, routes, call log, credits, compliance export.
8. **Phase 2 pieces** (build ahead, switch on later): own STIR/SHAKEN signing via a signing vendor,
   E911 address capture and validation per number, CPNI access controls and audit, CALEA request handling
   procedure, traceback response endpoint and runbook.

## Data rules

- Store E.164 numbers and transcripts only in the private tables; public views get SHA-256 hashes and `***-1234`.
- Keep call detail records for the retention period REGULATORY.md sets; never delete sealed log entries —
  redact the private table and keep the hash.
- Recording calls: Michigan is generally treated as one-party consent, but many states require all parties.
  Default: announce recording on every recorded call. Confirm with counsel (REGULATORY.md).

## Interfaces to keep stable

- MCP tools in `call-server` keep their names; new tools are added, not renamed.
- `/calls.json` and `/verify` formats are public contracts; version them if they change.
