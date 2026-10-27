package capmodel

import (
    "errors"
    "reflect"
    "testing"
)

// OFF-CHAIN model only. Invalid operations must be atomic and must not mutate
// lifetime issuance, outstanding supply, burned supply, or remaining capacity.
func TestRejectedOperationsLeaveLedgerUnchanged(t *testing.T) {
    ledger := mustLedger(t, "999999999999999999999999999")
    tests := []struct {
        name string
        apply func() error
        want error
    }{
        {"over-cap mint", func() error { _, err := ledger.Mint("2"); return err }, ErrLifetimeCapExceeded},
        {"oversized burn", func() error { _, err := ledger.Burn(MaximumBase); return err }, ErrInsufficientSupply},
        {"zero mint", func() error { _, err := ledger.Mint("0"); return err }, ErrInvalidAmount},
        {"negative burn", func() error { _, err := ledger.Burn("-1"); return err }, ErrInvalidAmount},
        {"noncanonical mint", func() error { _, err := ledger.Mint("01"); return err }, ErrInvalidAmount},
    }
    for _, tc := range tests {
        t.Run(tc.name, func(t *testing.T) {
            before := ledger.Snapshot()
            if err := tc.apply(); !errors.Is(err, tc.want) {
                t.Fatalf("expected %v, got %v", tc.want, err)
            }
            after := ledger.Snapshot()
            if !reflect.DeepEqual(before, after) {
                t.Fatalf("rejected operation mutated ledger: before=%+v after=%+v", before, after)
            }
        })
    }
}
