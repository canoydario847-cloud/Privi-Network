package capmodel

import (
    "errors"
    "sync"
    "math/big"
    "testing"
)

// OFF-CHAIN reference-model concurrency check; not proof of consensus safety.
func TestConcurrentFinalBaseUnitOnlyOneMintSucceeds(t *testing.T) {
    ledger := mustLedger(t, "999999999999999999999999999")
    const attempts = 64
    start := make(chan struct{})
    results := make(chan error, attempts)
    var wg sync.WaitGroup
    for i := 0; i < attempts; i++ {
        wg.Add(1)
        go func() {
            defer wg.Done()
            <-start
            _, err := ledger.Mint("1")
            results <- err
        }()
    }
    close(start)
    wg.Wait()
    close(results)
    accepted, rejected := 0, 0
    for err := range results {
        switch {
        case err == nil:
            accepted++
        case errors.Is(err, ErrLifetimeCapExceeded):
            rejected++
        default:
            t.Fatalf("unexpected mint result: %v", err)
        }
    }
    if accepted != 1 || rejected != attempts-1 {
        t.Fatalf("expected one accepted mint and %d rejected, got %d/%d", attempts-1, accepted, rejected)
    }
    snapshot := ledger.Snapshot()
    issued, ok := new(big.Int).SetString(snapshot.LifetimeIssued, 10)
    if !ok { t.Fatal("invalid lifetime issuance decimal") }
    outstanding, ok := new(big.Int).SetString(snapshot.Outstanding, 10)
    if !ok { t.Fatal("invalid outstanding decimal") }
    burned, ok := new(big.Int).SetString(snapshot.Burned, 10)
    if !ok { t.Fatal("invalid burned decimal") }
    if new(big.Int).Sub(issued, burned).Cmp(outstanding) != 0 {
        t.Fatalf("concurrent issuance violated accounting conservation: %+v", snapshot)
    }
    if snapshot.LifetimeIssued != MaximumBase || snapshot.Outstanding != MaximumBase ||
        snapshot.RemainingToMint != "0" {
        t.Fatalf("concurrent final-unit issuance broke cap: %+v", snapshot)
    }
}
