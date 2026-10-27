package capmodel

import (
    "errors"
    "testing"
)

// Off-chain reference-model test only: this does not establish consensus
// integration, validator independence, or production mainnet readiness.
func TestCapExhaustionAcrossMintAndBurnSequences(t *testing.T) {
    for _, tc := range []struct {
        name string
        genesis string
        mint string
        burn string
    }{
        {"one_base_unit_remaining", "999999999999999999999999999", "1", "1"},
        {"half_supply_then_fill", "500000000000000000000000000", "500000000000000000000000000", "1"},
        {"near_cap_burn_then_fill", "999999999999999999999999998", "2", "2"},
    } {
        t.Run(tc.name, func(t *testing.T) {
            ledger := mustLedger(t, tc.genesis)
            if _, err := ledger.Mint(tc.mint); err != nil { t.Fatal(err) }
            if _, err := ledger.Burn(tc.burn); err != nil { t.Fatal(err) }
            before := ledger.Snapshot()
            if before.LifetimeIssued != MaximumBase || before.RemainingToMint != "0" {
                t.Fatalf("burn reopened lifetime issuance cap: %+v", before)
            }
            for _, amount := range []string{"1", tc.mint, MaximumBase} {
                if _, err := ledger.Mint(amount); !errors.Is(err, ErrLifetimeCapExceeded) {
                    t.Fatalf("mint %s after exhaustion: expected cap error, got %v", amount, err)
                }
                if after := ledger.Snapshot(); after != before {
                    t.Fatalf("rejected mint changed state: before=%+v after=%+v", before, after)
                }
            }
        })
    }
}
