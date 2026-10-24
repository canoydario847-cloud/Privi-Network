package prvicap

import (
    "errors"
    "math/big"
    "testing"

    sdkmath "cosmossdk.io/math"
)

// These are keeper-level rejection tests against a fake KV service.
// They are NOT an SDK transaction cache/commit rollback integration test.
func TestRejectedReconcileLeavesPersistentCapRecordUntouched(t *testing.T) {
    k, store, ctx := setup(t, whole(100))
    before := string(store.content[string(keyGenesis)])
    original, err := k.Snapshot(ctx)
    if err != nil { t.Fatal(err) }

    over := new(big.Int)
    over.SetString(whole(101), 10)
    actual := sdkmath.NewInt(99)

    for _, bank := range []fakeBank{
        {base: sdkmath.NewIntFromBigInt(over)},
        {base: sdkmath.NewIntFromBigInt(new(big.Int).Sub(over, big.NewInt(1))), actual: &actual},
    } {
        if err := k.Reconcile(ctx, bank); !errors.Is(err, ErrUnexpectedSupply) {
            t.Fatalf("expected supply rejection, got %v", err)
        }
        if got := string(store.content[string(keyGenesis)]); got != before {
            t.Fatal("rejected reconciliation modified persistent genesis cap record")
        }
        state, err := k.Snapshot(ctx)
        if err != nil || state != original {
            t.Fatalf("rejected reconciliation changed keeper state: %+v %v", state, err)
        }
    }
}
