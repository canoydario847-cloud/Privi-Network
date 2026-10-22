# Privi Call carrier — regulatory map

> Agents: this is a working map, not legal advice. Every filing is **STOP: Dario**, and Dario should confirm
> the plan with a telecom attorney before Phase 2. Re-check each item against fcc.gov before acting —
> rules in this area change often (see "Moving rules" below). Last checked: 2026-10-22.

## Phase 1 — reseller on a CPaaS (now)

Privi is the upstream provider's customer. The upstream carries the carrier obligations, but Privi still must:

- Follow the upstream's acceptable use and KYC rules (business identity, use case per number).
- **TCPA / telemarketing:** no automated or prerecorded calls or texts to mobiles without prior express consent
  (written consent for marketing); honor the National Do Not Call Registry and Privi's internal DNC list;
  calling hours 8 a.m.–9 p.m. destination local time. AI-generated voices count as "artificial" voices under the FCC's 2024 ruling.
- **SMS:** register an A2P 10DLC brand and campaigns (through the upstream) before business texting.
- **Call recording consent:** announce recording; treat all-party-consent states conservatively.
- **Privacy:** published privacy policy covering call logs, transcripts and the hashed public log.

## Phase 2 — Privi becomes a voice service provider in its own name

Prepare the documents and code in advance; Dario files.

| Obligation | What it is | Agent prep |
|---|---|---|
| **FCC Registration Number (FRN)** | ID for all FCC filings (CORES) | Checklist only |
| **Form 499-A / 499-Q** (USAC) | Telecom reporting worksheet; universal service contributions on interstate revenue | Revenue categorization script from billing data |
| **Robocall Mitigation Database (RMD)** | Every provider that originates, carries or terminates calls needs an entry; downstream providers may only accept traffic from listed providers; annual recertification | Draft robocall mitigation plan built on Passport/KYA/Mandates; KYC procedure |
| **STIR/SHAKEN** | Sign calls with caller-ID attestation. Since Sept 18, 2025 providers with an implementation obligation must use **their own SPC token and certificate**, not a third party's | Vendor comparison for signing service; attestation-level logic from number ownership |
| **Traceback** | Answer Industry Traceback Group requests promptly | `/admin/traceback` lookup + runbook |
| **911 (Kari's Law / RAY BAUM'S Act)** | Interconnected VoIP must deliver 911 with a dispatchable location; register/validate customer addresses | Address capture + validation per number; 911 provider comparison |
| **CPNI** | Protect customer proprietary network information; annual certification filed with the FCC | CPNI policy, access logging (Ledger already gives tamper-evident logs) |
| **CALEA** | Lawful intercept capability and a System Security and Integrity plan | Procedure doc; upstream/vendor capability check |
| **Disability access** | Section 255/TRS contributions via 499 | Note in 499 prep |
| **Form 477 / BDC** | Data collection where applicable | Check applicability |
| **Michigan** | Check MPSC requirements and the state 911 surcharge for VoIP service sold to Michigan customers | Research note with citations |

## Phase 3 — direct access to numbers

Interconnected VoIP providers can apply to the FCC for direct numbering authorization. Current rules require,
among other things: certifications under penalty of perjury that numbers will not be used for illegal
robocalls, spoofing or fraud; full STIR/SHAKEN compliance and an RMD filing; disclosure of investigations;
**foreign ownership disclosures with an ownership diagram**; and evidence of 911/NG911, CALEA, access
stimulation, Form 499 and Form 477 compliance. The FCC tightened these rules in late 2025.

## Moving rules to watch

- **RMD overhaul (FNPRM, Sept 2026):** the FCC proposed widening who must file (VoIP resellers, dialing
  platforms, cloud providers, call centers), replacing "reasonable steps" with "affirmative, effective measures",
  machine-readable mitigation plans, KYC disclosure, financial assurances for some filers, foreign-adversary
  attestations, and a removal framework. Privi's Passport/KYA/Mandates design fits this direction — note it in
  comments and pitch, but do not claim compliance with rules not yet adopted.
- STIR/SHAKEN extensions to non-IP networks and any change to third-party signing.

## Sources

- FCC RMD proposal summary: https://www.mintz.com/insights-center/viewpoints/2776/2026-09-28-fcc-proposes-major-expansion-robocall-mitigation
- FCC order text: https://docs.fcc.gov/public/attachments/FCC-26-49A1.pdf
- Third-party authentication rule: https://vantagepnt.com/news/fcc-limits-third-party-stir-shaken-authentication/
- Direct numbering rules: https://www.mintz.com/insights-center/viewpoints/2776/2025-12-29-fcc-tightens-direct-number-access-rules-voip-providers
- NANPA guide for interconnected VoIP: https://www.nanpa.com/sites/default/files/2024-07/GettingStartedInterconnectedVoIPProviders.pdf
