package prvicap

import (
    "errors"
    "math/big"
    "testing"

    sdkmath "cosmossdk.io/math"
    sdk "github.com/cosmos/cosmos-sdk/types"
    authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
    banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
)

// A non-native surplus cannot compensate for a missing aprvi at the exact cap.
// UncheckedSetBalance is used only to corrupt this disposable SDK test fixture.
func TestActualSDKBankExactCapNativeDeficitCrossDenomFailsClosed(t *testing.T) {
    h := newRealBankHarness(t)
    max, ok := new(big.Int).SetString(MaxBase, 10)
    if !ok {
        t.Fatal("invalid embedded native PRVI maximum")
    }
    addr := authtypes.NewModuleAddress("exactcapdeficit")
    initial := sdk.NewCoins(
        sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max)),
        sdk.NewInt64Coin("uother", 50),
    )
    h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
        Params: banktypes.DefaultParams(),
        Balances: []banktypes.Balance{{Address: addr.String(), Coins: initial}},
        Supply: initial,
    })
    if err := h.cap.InitGenesis(h.ctx, MaxBase, h.bank); err != nil {
        t.Fatalf("valid exact-cap genesis rejected: %v", err)
    }

    less := new(big.Int).Sub(max, big.NewInt(1))
    if err := h.bank.UncheckedSetBalance(h.ctx, addr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(less))); err != nil {
        t.Fatalf("could not construct native deficit: %v", err)
    }
    if err := h.bank.UncheckedSetBalance(h.ctx, addr, sdk.NewInt64Coin("uother", 51)); err != nil {
        t.Fatalf("could not construct unrelated surplus: %v", err)
    }
    if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != MaxBase {
        t.Fatalf("declared native supply unexpectedly changed: %s", got)
    }
    // Verify both fixture mutations really occurred while the declared
    // counters stayed unchanged; otherwise this regression could pass vacuously.
    if got := h.bank.GetBalance(h.ctx, addr, BaseDenom).Amount.String(); got != less.String() {
        t.Fatalf("native deficit fixture missing: got %s, want %s", got, less.String())
    }
    if got := h.bank.GetBalance(h.ctx, addr, "uother").Amount.String(); got != "51" {
        t.Fatalf("unrelated surplus fixture missing: got %s, want 51", got)
    }
    if got := h.bank.GetSupply(h.ctx, "uother").Amount.String(); got != "50" {
        t.Fatalf("unrelated declared supply unexpectedly changed: %s", got)
    }
    if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
        t.Fatalf("unrelated surplus concealed native deficit: %v", err)
    }
    if state, err := h.cap.Snapshot(h.ctx); err != nil ||
        state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
        t.Fatalf("rejected deficit changed issuance: %+v, %v", state, err)
    }
    if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
        t.Fatalf("native mint allowed after deficit: %v", err)
    }
    if err := h.bank.UncheckedSetBalance(h.ctx, addr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max))); err != nil {
        t.Fatalf("could not restore native balance: %v", err)
    }
    if err := h.bank.UncheckedSetBalance(h.ctx, addr, sdk.NewInt64Coin("uother", 50)); err != nil {
        t.Fatalf("could not restore unrelated balance: %v", err)
    }
    // A successful recovery must not rewrite the lifetime issuance record.
    if got := h.bank.GetSupply(h.ctx, "uother").Amount.String(); got != "50" {
        t.Fatalf("unrelated declared supply changed during recovery: %s", got)
    }
    if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
        t.Fatalf("restored exact-cap balances rejected: %v", err)
    }
    if state, err := h.cap.Snapshot(h.ctx); err != nil ||
        state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
        t.Fatalf("recovery changed immutable issuance: %+v, %v", state, err)
    }
    // Recovery must not silently re-enable minting at the exact cap.
    if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
        t.Fatalf("recovery re-enabled native minting: %v", err)
    }
}
