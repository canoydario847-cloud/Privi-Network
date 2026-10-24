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
