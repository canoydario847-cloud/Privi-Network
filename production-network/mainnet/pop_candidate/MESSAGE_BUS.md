# PoP research message bus

**RESEARCH ONLY.** Not production P2P, not gossip security, not mainnet.

## Modules

| File | Role |
| --- | --- |
| `message_bus.cjs` | In-process bus: pub/sub, latency, drop rate, partition, **latency metrics** |
| `bus_driver.cjs` | `ResearchBusPeer` wires `ResearchRoundMachine` to the bus |
| `test_bus_driver.cjs` | Happy path + partition |
| `test_message_bus_latency.cjs` | Percentiles, configured delay, stats plumbing |
| `explore_latency.mjs` | CLI table: cfg latency vs measured p50/p95 and e2e |

## Latency metrics (research)

Each delivered message records `publishedAt`, `deliveredAt`, and `latencyMs`.

`bus.latencyMetrics()` / `bus.stats().latency` returns:

- `configuredLatencyMs`, `dropRate`
- `overall`: count, min, max, mean, p50, p95, p99 (ms)
- `byType`: same summary for proposal / prevote / precommit / timeout
- `productionConsensus: false`

## Flow

1. Expected proposer publishes signed `proposal`.
2. Peers publish `prevote` → quorum → `precommit` → decide.
3. Local timeout → view-change.

## Test / explore

```bash
cd production-network/mainnet/pop_candidate
node --test test_bus_driver.cjs test_message_bus_latency.cjs
node explore_latency.mjs
```

Passing tests is **not** PoP deployment or PRVI evidence.
