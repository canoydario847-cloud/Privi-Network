# Disposable Local EVM Signed Transfer — Verified Evidence (2026-10-18 UTC)

**Result:** PASS for exactly one **ephemeral, valueless** upstream Cosmos EVM local developer transaction.

**Source:** [GitHub Actions run #169](https://github.com/canoydario847-cloud/Privi-Network/actions/runs/39081294993); run ID `39081294993`, job ID `117538581202`. The job and all steps concluded **success**. The actual signed transfer and receipt verification JSON appeared in the job logs at approximately `2026-10-18T00:08:09Z`.

| Field | Observed value |
| --- | --- |
| Cosmos developer chain ID | `local-4221` |
| Numeric EVM chain ID | `262144` |
| Asset | Disposable upstream `atest` developer TEST only, valueless |
| Transaction hash | `0x4867205324169187ff44315a81d95f373ae58fbb5c4c332c07cb1194adfb5d5d` |
| Sender (disposable test wallet) | `0xC6Fe5D33615a1C52c08018c47E8Bc53646A0E101` |
| Recipient (disposable test wallet) | `0xB528E984cbc2291b1AA70d70EEd800E8f6EfF38c` |
| Value transferred | `10000000000000` base units |
| Block height | `4` |
| Block confirmations | `2` |
| Recipient balance increase | `10000000000000` base units |
| Independent receipt-audit script | `PASS` |
| Overall transfer status in job logs | `REAL_DISPOSABLE_LOCAL_TEST_TRANSFER_VERIFIED` |

**What the successful CI run establishes:** The ephemeral upstream developer chain can sign and execute one positive-value native `atest` transfer and return a successful Ethereum receipt matching the expected sender, recipient, amount, block inclusion and confirmations. The recipient's balance increased by the transferred amount. The separate read-only receipt auditor corroborated the transaction against local RPC data. Four local CometBFT validators, Ethereum RPC and wallet read-only RPC checks also passed within the same job.

**What it does not establish:**
- The test blockchain was built and destroyed inside a GitHub-hosted **single-runner** job. The transaction hash is **not queryable from a persistent public blockchain explorer** after the job finishes.
- The four validator processes were **not** independently operated or geographically distributed.
- The evidence does not verify an operator-controlled public TESTnet, permanent network identity, faucet availability, independently signed genesis, contract deployment, sustained throughput, upgrades or fault recovery.
- This transaction involved **no native PRVI, no existing BNB PRIV, no real customer funds**, and makes no claim of PRVI genesis validity, staking or 1-billion lifetime hard-cap enforcement.
- It does **not** authorize activation of PRVI financial mainnet, token issuance, exchange listing or marketing any network as live.

## Gate decisions

- Local four-validator smoke test: **PASS**.
- Disposable, signed native transfer and independently checked receipt: **PASS**.
- Four **independent** public-testnet operators: **DEFERRED at owner's request; 0/4 independently verified; NOT SATISFIED**.
- Real multi-host public TESTnet: **NOT DEPLOYED**.
- Financial PRVI mainnet: **NO-GO**, requiring separate audited binary, reviewed production genesis and supply cap, independent validators, security review, legal review and final sign-off.

Re-run against a real public TESTnet only after explicit operator onboarding, reviewed network chain IDs, independently verified genesis and secure node deployments. **Never reuse the disposable test keys**.
