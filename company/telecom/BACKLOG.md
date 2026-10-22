# Privi Call carrier — backlog

Order matters. Each item is one PR unless noted. Use `company/templates/AGENT_TASK.md` when expanding an item.
**STOP: Dario** = prepare, list in the PR under "Needs Dario", stop.

## Now (Phase 1)

- [x] T0. Trial mode for the phone line (`CALL_PHONE_TRIAL`): number hidden from public pages while on the Twilio free trial.
- [ ] **STOP: Dario** — start the Twilio free trial and test privately (steps in `call-server/README.md`, "Start on the Twilio free trial"). Trial ends 30 days after sign-up.
- [ ] **STOP: Dario** — after the trial works: upgrade, buy the Privi phone number (810 area code fits Port Huron), set `CALL_PHONE_NUMBER` and `CALL_PHONE_TRIAL=false` on `privi-call` in Render.
- [ ] T1. Provider adapter interface + Twilio adapter (`providers/`), with fakes for tests. No live purchases in tests.
- [ ] T2. Numbers table and routing table; `/voice/inbound` routes by dialled number; default route = current Privi line.
- [ ] T3. MCP tools `number_search`, `number_list`, `number_route` (free) and `number_buy`, `number_release` (x402, closed until CDP keys).
- [ ] T4. Voice agent profiles per number (greeting, FAQ, hours, hand-off), editable through MCP and the dashboard.
- [ ] T5. ML-DSA-87 signature on each call record (reuse `quantum-server` attest code as a small shared module).
- [ ] T6. `sites/call/` dashboard page on priviflow.us: numbers, routes, live sealed log, credits.
- [ ] T7. Outbound `call_dial` gated by Passport score, Mandate, internal DNC list and destination calling hours; every refusal logged.
- [ ] T8. SMS on Privi numbers (inbound first). **STOP: Dario** for 10DLC brand/campaign registration.
- [ ] T9. Research: CPaaS comparison (VENDORS.md checklist) → `research/cpaas-comparison-<date>.md`.
- [ ] T10. Unit economics model → PRICING.md options for Dario.
- [ ] T11. Privacy policy and terms for Privi Call (draft for attorney review) in `sites/call/legal/`.

## Prepare Phase 2 (build ahead, file later)

- [ ] P1. Robocall mitigation plan draft built on Passport/KYA/Mandates + KYC procedure (`compliance/robocall-mitigation-plan.md`).
- [ ] P2. 911: address capture and validation per number; 911 vendor comparison.
- [ ] P3. CPNI policy + access logging through Ledger; annual certification draft.
- [ ] P4. Traceback lookup endpoint (admin) + runbook.
- [ ] P5. CALEA procedure doc and vendor capability check.
- [ ] P6. 499 revenue categorization from billing data.
- [ ] P7. STIR/SHAKEN signing vendor comparison and attestation-level logic.
- [ ] P8. Michigan research note (MPSC, state 911 surcharge for VoIP) with citations.
- [ ] **STOP: Dario** — attorney review; FRN; 499; RMD entry; SPC token; 911 provider contract.

## Later

- [ ] Number porting in/out.
- [ ] Direct numbering access application package (Phase 3).
- [ ] Quantum-secured calls and trunks with the quantum network (see `../quantum-networking/BACKLOG.md` Q8 and Phase 3).

## Funding that fits

NSF SBIR (verifiable AI-agent calling to fight robocalls), Michigan Rise Pre-Seed, Techstars Anywhere.
