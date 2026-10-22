# Agent task template

Copy this into a GitHub issue or a backlog item. An agent with no other context should be able to finish it.

```
## Goal
One sentence: what exists when this is done.

## Context
- Playbook section: company/<telecom|quantum-networking>/<FILE>.md#<section>
- Code to start from: <folder/file>
- Live service: <url>

## Done means
- [ ] <observable result, e.g. "POST /voice/inbound returns TwiML that ...">
- [ ] tests in <folder>/tests pass
- [ ] README / env vars documented
- [ ] BACKLOG item ticked

## Out of scope
What the agent must not do (spend, file, buy numbers, deploy outside Render).

## STOP: Dario
Anything that needs Dario's account, money, signature or a regulator filing. Prepare it, list it, stop.
```
