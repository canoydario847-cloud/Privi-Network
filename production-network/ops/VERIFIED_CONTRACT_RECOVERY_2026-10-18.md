# Verified disposable EVM contract and fault-recovery tests — 2026-10-18 UTC

**Verified result:** [GitHub Actions #176](https://github.com/canoydario847-cloud/Privi-Network/actions/runs/39086603186), integration job `117554437071`: **SUCCESS**. The offline test job also passed.

The job's actual JSON log output recorded the following evidence against **only an ephemeral, same-runner upstream Cosmos EVM developer network** (Cosmos ID `local-4221`; numeric EVM ID `262144`; native `atest` is valueless).

## 1. Actual Solidity contract deployment and state write — PASS

- Check status: `DISPOSABLE_LOCAL_EVM_CONTRACT_DEPLOY_AND_STATE_WRITE_VERIFIED`
- Solidity compiler: `0.8.26+commit.8a97fa7a.Emscripten.clang`
- Contract fixture: [PriviDevCounter.sol](../testnet/contracts/PriviDevCounter.sol), a **nonfinancial** counter without mint/sale features
- Solidity source SHA-256: `16a5f4d42092e21f0f3ac1bbc986f65a6ec917c59ea1699a9b268ce8a9a6a286`
- Deployed runtime code SHA-256: `7cd5aee0e5e5c7a15f03c78c34759838bc17f0690ccc92e0af7c7ed0a7f665c3`
- Contract address: `0x07Aa076883658B7ED99D25b1E6685808372C8fE2` **only on the destroyed local developer chain**
- Deployment transaction: `0xd33851e9604b88163efd37781230232b5b7415b2aa481b2171b46477e569baca` in block **7**, **2 confirmations**
- Contract state-write transaction: `0xb5dffd8067bff3d5d9f301956ccfc0347179ad8887abd17416c328dc31213d9f` in block **9**, **2 confirmations**
- Storage counter: **0 → 1**, event `Incremented` independently checked for correct caller and new value

## 2. Actual local validator outage and recovery — PASS

- Check status: `DISPOSABLE_LOCAL_VALIDATOR_OUTAGE_AND_RECOVERY_VERIFIED`
- Stopped disposable validator consensus address: `345A1EA46A07E6445BD0D9DD4B0AE43CCC542616`
- Before outage: at least block **10**
- During outage: verified block **13** committed with **3 of 4 validators**: voting power **300/400 = 75%**, exceeding the required 2/3
- After restart: block **15** committed with **4 of 4 validators**: voting power **400/400 = 100%**
- The restarted validator's consensus address was again present among successful commit signatures; all four local RPC observers agreed on the recovered block.

## Limitations and gates

These records are **not** PRVI token transfers, public testnet deployments, multi-machine failure-recovery results, independent validator proof, a financial token audit, or evidence of any production chain. CI destroyed the ephemeral blockchain after completion. The local transaction hashes and contract address are **not accessible as persistent public explorer links**.

Operator recruitment remains deferred at the owner's request, **not waived**: independently verified public validator count remains **0/4**. Full public multi-host testnet, audited/custom PRVI binary, 1-billion hard cap proof, signed production genesis, independent auditors and final legal/technical approval remain incomplete.

**Financial PRVI mainnet: NO-GO / not activated.**
