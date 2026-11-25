# PoP research multi-worker bus

**RESEARCH ONLY.** Uses Node `worker_threads` as isolated peers + host relay.
Not production P2P, not mainnet, not PRVI.

## Modules

| File | Role |
| --- | --- |
| `worker_bus.cjs` | Host: spawns workers, central `ResearchMessageBus` fan-out |
| `worker_peer_boot.cjs` | Worker entry: local `ResearchRoundMachine`, signs, publishes |
| `test_worker_bus.cjs` | 4-worker decision tests |

## Flow

1. Host starts one worker per validator (PKCS8 key in `workerData`).
2. Worker posts `publish` envelopes to host.
3. Host runs them through `ResearchMessageBus` (latency/drop metrics apply).
4. Host fans `envelope` messages to all workers.
5. Workers decide independently; host collects `decided` events.

## Test

```bash
cd production-network/mainnet/pop_candidate
node --test test_worker_bus.cjs
```

Passing is **not** evidence of live PoP finality.
