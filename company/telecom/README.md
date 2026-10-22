# Privi Call carrier — playbook

**Goal:** turn Privi Call from an agent call network with one phone line into a real calling company:
Privi phone numbers for businesses and AI agents, inbound and outbound voice and SMS, every call sealed
in a tamper-evident log, priced as cheap as possible while still making money.

**What makes Privi different from Twilio or a VoIP reseller:** every call carries proof. Each call record is
hash-chained and anchored on chain; each AI agent that places a call is bound to a Privi Passport (KYA);
outbound calls by agents run inside human-signed Mandates. That is a direct answer to the robocall problem
regulators are pressing carriers on — "Know Your Agent" for voice.

## Files

| File | What it is for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Target system: numbers, SIP, media, AI voice agents, sealed log, billing |
| [REGULATORY.md](REGULATORY.md) | What a US voice provider must register, file and build, by phase |
| [VENDORS.md](VENDORS.md) | Upstream carriers and services to build on, and what to compare |
| [PRICING.md](PRICING.md) | Unit economics and price list method |
| [BACKLOG.md](BACKLOG.md) | Ordered tasks for agents, with **STOP: Dario** points |

## The four phases

| Phase | Privi is legally | Numbers come from | What ships | Gate to the next phase |
|---|---|---|---|---|
| **1. Reseller on a CPaaS** (now) | A customer of Twilio/Telnyx/Bandwidth | The upstream provider, in Privi's account | Privi phone line, Privi numbers for agents (sub-accounts), AI receptionist, sealed log, x402 billing | 25 paying number customers or a pilot that needs Privi's own name on calls |
| **2. Interconnected VoIP provider** | A registered voice service provider | Still upstream | Privi's own FCC registrations, own STIR/SHAKEN certificate, Robocall Mitigation Database entry, 911 and CPNI programs | Volume where wholesale rates beat CPaaS retail |
| **3. Direct numbering access** | VoIP provider holding its own number blocks | NANPA / Pooling Administrator, under FCC authorization | Number inventory, porting, Michigan-first local numbers | Need for own switching / interconnection |
| **4. Facilities / CLEC** (optional) | Competitive local exchange carrier in Michigan | Own | Own interconnection, possibly quantum-secured trunks (see `../quantum-networking/`) | — |

Agents work Phase 1 now and **prepare** Phase 2 (documents, policies, code) so Dario can file when he decides.

## How the phone line works today

`call-server/` already answers a Twilio number at `/voice/inbound`, runs a scripted voice agent, takes
pilot requests, forwards "Dario" or 0 to +1 313-413-8532, and logs every turn into the sealed call log
(phone numbers masked publicly). Twilio auth token and the number are set in Render by Dario.
See `call-server/README.md`.
