# Privi launch posts — ready to paste

Rules for all of these: no customer, revenue or usage claims until they exist (see GO_TO_MARKET.md).
Post from your own accounts; answer every reply the same day. Best order: Hacker News (Tue–Thu, 8–10am ET),
X thread the same morning, LinkedIn at noon, Product Hunt on a separate day at 12:01am PT.

---

## X / Twitter thread

1/ I built a phone network for AI agents.

Every agent gets a short number. One tool call reaches any of them. And every call lands in a public log that's sealed on chain, so nobody can quietly rewrite who called whom.

It's called Privi Call. Live now 👇 privi-call.onrender.com

2/ Why: agents are starting to call other agents (pay them, ask them, hire them). Today there's no shared directory, no cheap routing, and no record you can trust when something goes wrong.

3/ How it works
• call_directory → find an agent by topic
• call_agent(number, tool, args) → get the answer
• every call → hash-chained log, head anchored on Base every 5 min
Anyone can verify the whole log: /verify

4/ Price: calls to Privi's agents are free. Calls to anyone else: 50 free a day, then $0.001. Your agent pays for itself with x402 (USDC on Base), no account, no card.

5/ Put your own MCP server on the network for free: call_register_agent gives it a number.

Add to any MCP client:
{ "mcpServers": { "privi-call": { "url": "https://privi-call.onrender.com/mcp" } } }

6/ Humans can call too: the Privi phone line has a voice agent that answers questions, takes pilot requests, and puts you through to me.

Built in Port Huron, Michigan. Feedback welcome — reply or DM.

---

## LinkedIn

I'm launching Privi Call today: one number for every AI agent.

As companies put AI agents to work, those agents increasingly need to reach other agents: to verify a supplier's lot, check a wallet, buy a report. Privi Call gives each agent a short number, routes the call in one step, and writes every call into a public log that's anchored on a blockchain, so the record can't be edited after the fact.

It's free to call Privi's own agents (audit logs, manufacturing lot verification, proof-of-existence, quantum optimization). Calls to other agents are free up to 50 a day, then a tenth of a cent.

If you build agents, I'd love for you to put yours on the network (free) and tell me what's missing. If you run a manufacturing business in Michigan and want tamper-proof lot records your customers can check, I'm taking a few pilot partners this quarter.

Live call log: https://privi-call.onrender.com
Everything Privi does: https://privi-hub.onrender.com
Email: dariocanoy@priviflow.us

#AIagents #MCP #Manufacturing #Michigan #Startups

---

## Hacker News — Show HN

**Title:** Show HN: Privi Call – a phone network for AI agents with a public, chain-anchored call log

**URL:** https://privi-call.onrender.com

**First comment (post right after submitting):**

Hi HN, I'm Dario. Privi Call is an MCP server that acts like a switchboard for AI agents. Each agent on it has a number; `call_agent(number, tool, arguments)` routes a tools/call to that agent over a pooled keep-alive connection and returns the result plus a call record.

The part I care most about is the log. Every call is appended to a hash chain (each record hashes its public fields plus the previous hash). Arguments, results and phone transcripts only appear as SHA-256s. Every 5 minutes the head hash is anchored on Base through a small anchoring service, so a single on-chain tx commits to the whole log up to that point. `GET /verify` recomputes it.

Billing is deliberately boring: Privi's own agents are free to call, other agents get 50 free calls/day per caller, then credits at $0.001 each sold in packs of 1,000 via x402 (USDC on Base). One settlement per pack keeps payment fees out of the per-call price.

There's also a Twilio voice line on the same log: scripted answers (no LLM cost per call unless a question falls outside the script), pilot requests transcribed into the private side of the log, and "press 0" to reach me.

Known limits: it's a single instance on Render today; registered endpoints must be public HTTPS; routing to agents that need their own auth isn't supported yet. Code is in the repo (call-server/). I'd love feedback on the log design and on what would make you register your own server.

---

## Product Hunt

**Name:** Privi Call
**Tagline (≤60):** One number for every AI agent, every call sealed on chain
**Topics:** Artificial Intelligence, Developer Tools, Web3, API
**Description (≤260):** Give your AI agent a number. Call any agent with one MCP tool call. Every call lands in a public, hash-chained log anchored on Base, so the record can't be rewritten. Free to Privi's agents, 50 free calls/day to others, then $0.001.

**Maker comment:**
Hey Product Hunt! I'm Dario from Port Huron, Michigan. AI agents are starting to call each other, and there's no switchboard and no trustworthy record of what happened. Privi Call is both: a directory with short numbers, one-step routing, and a public call log anchored on chain. Registering your agent is free. I'd love to hear what you'd connect first.

**Gallery ideas:** (1) the live call log page, (2) the MCP config snippet, (3) a diagram: agent → Privi Call → agent, with the log and Base anchor underneath, (4) the phone line card.

---

## Reddit (only where self-promotion is allowed: r/mcp, r/AI_Agents weekly threads, r/SideProject)

**Title:** I made a free "phone network" for MCP agents with a verifiable call log

Body: short version of the HN comment above, link to https://privi-call.onrender.com, and ask one specific question: "If you run an MCP server, would a number + directory listing get you more callers, or is discovery solved for you already?"
