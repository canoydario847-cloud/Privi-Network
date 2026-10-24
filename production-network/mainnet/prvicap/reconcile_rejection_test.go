package prvicap

import (
    "errors"
    "math/big"
    "testing"
    "context"

    sdk "github.com/cosmos/cosmos-sdk/types"

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


// Multi-account coverage matters because a correct supply index alone does not
// prove that the sum of user and module account balances is conserved.
// This uses a fake bank, NOT a full SDK state-machine or rollback integration.
type multiAccountBank struct {
    declared sdkmath.Int
    balances []sdk.Coin
}
func (b multiAccountBank) GetSupply(_ context.Context, denom string) sdk.Coin {
    return sdk.NewCoin(denom, b.declared)
}
func (b multiAccountBank) IterateAllBalances(_ context.Context, cb func(sdk.AccAddress, sdk.Coin) bool) {
    for i, coin := range b.balances {
        addr := sdk.AccAddress(make([]byte, 20))
        addr[19] = byte(i + 1)
        if cb(addr, coin) { return }
    }
}
func TestNativeSupplyMatchesSumAcrossAccounts(t *testing.T) {
    declared := sdkmath.NewInt(1000)
    cases := []struct {
        name string
        balances []sdk.Coin
        reject bool
    }{
        {"user and module accounts plus unrelated denom", []sdk.Coin{
            sdk.NewInt64Coin(BaseDenom, 400),
            sdk.NewInt64Coin("other", 123),
            sdk.NewInt64Coin(BaseDenom, 600),
        }, false},
        {"extra native unit in second account", []sdk.Coin{
            sdk.NewInt64Coin(BaseDenom, 400),
            sdk.NewInt64Coin("other", 123),
            sdk.NewInt64Coin(BaseDenom, 601),
        }, true},
        {"missing native unit in second account", []sdk.Coin{
            sdk.NewInt64Coin(BaseDenom, 400),
            sdk.NewInt64Coin("other", 123),
            sdk.NewInt64Coin(BaseDenom, 599),
        }, true},
    }
    for _, tc := range cases {
        t.Run(tc.name, func(t *testing.T) {
            bank := multiAccountBank{declared: declared, balances: tc.balances}
            store := newFakeKV()
            keeper, err := New(fakeService{store})
            if err != nil { t.Fatal(err) }
            ctx := context.Background()
            err = keeper.InitGenesis(ctx, declared.String(), bank)
            if tc.reject {
                if !errors.Is(err, ErrBankSupplyMismatch) { t.Fatalf("bad multi-account genesis accepted: %v", err) }
                if len(store.content) != 0 { t.Fatal("rejected genesis persisted cap state") }
                return
            }
            if err != nil { t.Fatalf("valid multi-account genesis rejected: %v", err) }
            if err := keeper.Reconcile(ctx, bank); err != nil { t.Fatalf("valid multi-account reconciliation rejected: %v", err) }
        })
    }
}

// A full native burn must not erase the immutable genesis issuance record.
// This is a fake-bank/KV regression, not an SDK cache-context integration test.
func TestFullBurnToZeroCannotResetNativeIssuance(t *testing.T) {
    initial := whole(100)
    keeper, store, ctx := setup(t, initial)
    burned := fakeBank{base: sdkmath.ZeroInt()}
    if err := keeper.Reconcile(ctx, burned); err != nil {
        t.Fatalf("full native burn rejected: %v", err)
    }
    reopened, err := New(fakeService{store})
    if err != nil { t.Fatal(err) }
    state, err := reopened.Snapshot(ctx)
    if err != nil || state.LifetimeIssuedBase != initial {
        t.Fatalf("burn erased immutable issuance history: %+v, %v", state, err)
    }
    if err := reopened.MintRestriction(ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
        t.Fatalf("native remint after complete burn was permitted: %v", err)
    }
    if err := reopened.InitGenesis(ctx, whole(1), fakeBank{base: sdkmath.NewIntFromBigInt(big.NewInt(1_000_000_000_000_000_000))}); !errors.Is(err, ErrAlreadyInitialized) {
        t.Fatalf("repeated genesis after full burn was permitted: %v", err)
    }
}


// A zero bank supply after a complete burn must not mask an unauthorized
// direct native balance write. The immutable issuance record is preserved.
// Fake-bank test only; it does not prove SDK cache-context rollback.
func TestZeroSupplyRejectsHiddenNativeBalanceAfterFullBurn(t *testing.T) {
    k, store, ctx := setup(t, whole(100))
    original, err := k.Snapshot(ctx)
    if err != nil { t.Fatal(err) }
    before := string(store.content[string(keyGenesis)])

    // A legitimate complete burn has zero supply and zero account balances.
    if err := k.Reconcile(ctx, fakeBank{base: sdkmath.ZeroInt()}); err != nil {
        t.Fatalf("valid complete burn rejected: %v", err)
    }
    // Simulate an unchecked balance setter adding one aprvi without
    // updating x/bank's declared zero supply.
    hidden := sdkmath.NewInt(1)
    err = k.Reconcile(ctx, fakeBank{base: sdkmath.ZeroInt(), actual: &hidden})
    if !errors.Is(err, ErrUnexpectedSupply) {
        t.Fatalf("hidden native balance after full burn accepted: %v", err)
    }
    if got := string(store.content[string(keyGenesis)]); got != before {
        t.Fatal("rejected hidden balance changed immutable issuance state")
    }
    after, err := k.Snapshot(ctx)
    if err != nil || after != original {
        t.Fatalf("reconciliation changed immutable cap: %+v %v", after, err)
    }
}


// This is a fake-KV/SDK-typed keeper regression, NOT proof of production
// consensus transaction rollback or protection against same-block mint+burn.
func TestNativeSupplyCannotReboundAfterObservedBurn(t *testing.T) {
    k, store, ctx := setup(t, whole(100))
    bank := func(n int64) fakeBank {
        amount, ok := new(big.Int).SetString(whole(n), 10)
        if !ok { t.Fatal("invalid test amount") }
        return fakeBank{base: sdkmath.NewIntFromBigInt(amount)}
    }
    if err := k.Reconcile(ctx, bank(90)); err != nil {
        t.Fatalf("valid native burn rejected: %v", err)
    }
    observed := string(store.content[string(keyObservedSupply)])
    if observed != whole(90) { t.Fatalf("burn observation missing: %q", observed) }
    // Rebound is below genesis (100) but above the last validated 90.
    if err := k.Reconcile(ctx, bank(91)); !errors.Is(err, ErrUnexpectedSupply) {
        t.Fatalf("cross-block native supply rebound accepted: %v", err)
    }
    if got := string(store.content[string(keyObservedSupply)]); got != observed {
        t.Fatal("rejected rebound modified last observed supply")
    }
    if err := k.Reconcile(ctx, bank(90)); err != nil {
        t.Fatalf("unchanged native supply rejected: %v", err)
    }
    if err := k.Reconcile(ctx, bank(89)); err != nil {
        t.Fatalf("second valid burn rejected: %v", err)
    }
    if err := k.Reconcile(ctx, bank(90)); !errors.Is(err, ErrUnexpectedSupply) {
        t.Fatalf("rebound after second burn accepted: %v", err)
    }
    reopened, err := New(fakeService{store})
    if err != nil { t.Fatal(err) }
    if err := reopened.Reconcile(ctx, bank(90)); !errors.Is(err, ErrUnexpectedSupply) {
        t.Fatalf("reopened keeper forgot observed burn: %v", err)
    }
}

func TestCorruptObservedSupplyFailsClosed(t *testing.T) {
    k, store, ctx := setup(t, whole(100))
    for _, invalid := range []string{"", "-1", "00", "001", "abc", whole(101)} {
        store.content[string(keyObservedSupply)] = []byte(invalid)
        if err := k.Reconcile(ctx, fakeBank{base: sdkmath.ZeroInt()}); !errors.Is(err, ErrStoreCorrupt) {
            t.Fatalf("corrupt observed supply %q accepted: %v", invalid, err)
        }
    }
}
