package capmodel

import (
    "errors"
    "math/big"
    "sync"
    "testing"
)

// OFF-CHAIN reference-model test only. The lifetime issuance limit must hold
// even when a partially issued supply receives concurrent mints and burns.
func TestConcurrentPartialCapMixedOperations(t *testing.T) {
    const initial = "999999999999999999999999990"
    ledger := mustLedger(t, initial)
    const mintAttempts = 64
    const burnAttempts = 32
    start := make(chan struct{})
    results := make(chan struct{ mint bool; err error }, mintAttempts+burnAttempts)
    var wg sync.WaitGroup
    for i := 0; i < mintAttempts+burnAttempts; i++ {
        mint := i < mintAttempts
        wg.Add(1)
        go func(mint bool) {
            defer wg.Done()
            <-start
            if mint {
                _, err := ledger.Mint("1")
                results <- struct{ mint bool; err error }{true, err}
            } else {
                _, err := ledger.Burn("1")
                results <- struct{ mint bool; err error }{false, err}
            }
        }(mint)
    }
    close(start)
    wg.Wait()
    close(results)
    minted, burned, rejected := 0, 0, 0
    for result := range results {
        if result.mint {
            switch {
            case result.err == nil: minted++
            case errors.Is(result.err, ErrLifetimeCapExceeded): rejected++
            default: t.Fatalf("unexpected mint error: %v", result.err)
            }
        } else {
            if result.err != nil { t.Fatalf("unexpected burn error: %v", result.err) }
            burned++
        }
    }
    if minted != 10 || rejected != mintAttempts-10 || burned != burnAttempts {
        t.Fatalf("minted=%d rejected=%d burned=%d", minted, rejected, burned)
    }
    snap := ledger.Snapshot()
    issued, ok := new(big.Int).SetString(snap.LifetimeIssued, 10)
    if !ok { t.Fatal("invalid issued amount") }
    outstanding, ok := new(big.Int).SetString(snap.Outstanding, 10)
    if !ok { t.Fatal("invalid outstanding amount") }
    burns, ok := new(big.Int).SetString(snap.Burned, 10)
    if !ok { t.Fatal("invalid burned amount") }
    if snap.LifetimeIssued != MaximumBase || snap.RemainingToMint != "0" ||
        burns.Int64() != burnAttempts ||
        new(big.Int).Sub(issued, burns).Cmp(outstanding) != 0 {
        t.Fatalf("mixed concurrent operations broke supply invariants: %+v", snap)
    }
}
