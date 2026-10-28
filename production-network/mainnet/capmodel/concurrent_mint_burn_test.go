package capmodel

import (
    "errors"
    "sync"
    "testing"
)

// OFF-CHAIN model only. Burned coins must never reopen the lifetime issuance cap,
// even when burns race with new mint attempts.
func TestConcurrentMintAndBurnNeverReopensLifetimeCap(t *testing.T) {
    ledger := mustLedger(t, MaximumBase)
    const attempts = 64
    start := make(chan struct{})
    results := make(chan error, attempts)
    var wg sync.WaitGroup
    for i := 0; i < attempts; i++ {
        wg.Add(1)
        if i%2 == 0 {
            go func() {
                defer wg.Done()
                <-start
                _, err := ledger.Burn("1")
                results <- err
            }()
        } else {
            go func() {
                defer wg.Done()
                <-start
                _, err := ledger.Mint("1")
                results <- err
            }()
        }
    }
    close(start)
    wg.Wait()
    close(results)
    successfulBurns, rejectedMints := 0, 0
    for err := range results {
        switch {
        case err == nil:
            successfulBurns++
        case errors.Is(err, ErrLifetimeCapExceeded):
            rejectedMints++
        default:
            t.Fatalf("unexpected concurrent operation result: %v", err)
        }
    }
    if successfulBurns != attempts/2 || rejectedMints != attempts/2 {
        t.Fatalf("unexpected successful burns/rejected mints: %d/%d", successfulBurns, rejectedMints)
    }
    snap := ledger.Snapshot()
    if snap.LifetimeIssued != MaximumBase || snap.RemainingToMint != "0" ||
        snap.Burned != "32" || snap.Outstanding != "999999999999999999999999968" {
        t.Fatalf("concurrent burn and mint violated lifetime cap: %+v", snap)
    }
}
