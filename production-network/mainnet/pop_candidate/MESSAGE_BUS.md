# PoP research message bus

**RESEARCH ONLY.** Not production P2P, not gossip security, not mainnet.

## Modules

| File | Role |
| --- | --- |
| `message_bus.cjs` | In-process bus: publish/subscribe, optional latency, drop rate, partition set |
| `bus_driver.cjs` | `ResearchBusPeer` wires `ResearchRoundMachine` to the bus; `runResearchHeight` helper |
| `test_bus_driver.cjs` | Happy path (4 peers decide), partition isolation |

## Flow

1. Expected proposer publishes a signed `proposal`.
2. Each peer runs `onProposal`, publishes a signed `prevote`.
3. On prevote quorum → `onPrevoteQuorum` → publish `precommit`.
4. On precommit quorum → decide (`productionConsensus: false`).
5. Local timers call `onTimeout` → next round → new proposer may publish.

## Test

```bash
cd production-network/mainnet/pop_candidate
node --test test_bus_driver.cjs
```

Passing tests does **not** mean PoP is deployed or PRVI is live.
