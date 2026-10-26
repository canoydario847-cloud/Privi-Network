package capmodel

import (
    "errors"
    "math/big"
    "math/rand"
    "testing"
)

// This is an OFF-CHAIN model test only. It cannot prove Cosmos SDK mint-route
// coverage, persisted consensus state, upgrade safety or mainnet readiness.
func TestDeterministicIssuanceInvariantSequences(t *testing.T) {
    cap, ok := new(big.Int).SetString(MaximumBase, 10)
    if !ok { t.Fatal("invalid cap constant") }
    for seed := int64(0); seed < 32; seed++ {
        rng := rand.New(rand.NewSource(seed))
        ledger := mustLedger(t, "1")
        issued := big.NewInt(1)
        outstanding := big.NewInt(1)
        burned := new(big.Int)
        for step := 0; step < 300; step++ {
            amount := big.NewInt(rng.Int63n(1_000_000_000_000_000_000) + 1)
            previous := ledger.Snapshot()
            if rng.Intn(2) == 0 {
                next := new(big.Int).Add(issued, amount)
                _, err := ledger.Mint(amount.String())
                if next.Cmp(cap) > 0 {
                    if !errors.Is(err, ErrLifetimeCapExceeded) { t.Fatalf("seed=%d step=%d: expected cap rejection, got %v", seed, step, err) }
                    if ledger.Snapshot() != previous { t.Fatal("rejected mint changed state") }
                } else {
                    if err != nil { t.Fatal(err) }
                    issued.Set(next)
                    outstanding.Add(outstanding, amount)
                }
            } else {
                _, err := ledger.Burn(amount.String())
                if amount.Cmp(outstanding) > 0 {
                    if !errors.Is(err, ErrInsufficientSupply) { t.Fatalf("expected burn rejection: %v", err) }
                    if ledger.Snapshot() != previous { t.Fatal("rejected burn changed state") }
                } else {
                    if err != nil { t.Fatal(err) }
                    outstanding.Sub(outstanding, amount)
                    burned.Add(burned, amount)
                }
            }
            snap := ledger.Snapshot()
            if snap.LifetimeIssued != issued.String() || snap.Outstanding != outstanding.String() ||
                snap.Burned != burned.String() || snap.RemainingToMint != new(big.Int).Sub(cap, issued).String() {
                t.Fatalf("seed=%d step=%d: accounting mismatch: %+v", seed, step, snap)
            }
            if new(big.Int).Sub(issued, burned).Cmp(outstanding) != 0 || issued.Cmp(cap) > 0 {
                t.Fatalf("seed=%d step=%d: invariant violation", seed, step)
            }
        }
    }
}
