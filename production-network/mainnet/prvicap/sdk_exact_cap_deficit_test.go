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
    // Reconciliation must remain fail-closed on repeated checks of the same
    // corrupted state; an earlier rejection must not mark it as repaired.
    if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
        t.Fatalf("repeated reconciliation accepted unresolved native deficit: %v", err)
    }
    // Failed reconciliation must not mutate either corrupted account balance.
    // The discrepancy must remain observable until an explicit repair occurs.
    if got := h.bank.GetBalance(h.ctx, addr, BaseDenom).Amount.String(); got != less.String() {
        t.Fatalf("rejected deficit modified native account balance: got %s, want %s", got, less.String())
    }
    if got := h.bank.GetBalance(h.ctx, addr, "uother").Amount.String(); got != "51" {
        t.Fatalf("rejected deficit modified unrelated account balance: got %s, want 51", got)
    }
    // Failed checks must not silently repair the bank supply counters.
    if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != MaxBase {
        t.Fatalf("rejected deficit changed declared native supply: %s", got)
    }
    if got := h.bank.GetSupply(h.ctx, "uother").Amount.String(); got != "50" {
        t.Fatalf("rejected deficit changed unrelated declared supply: %s", got)
    }
    // A second rejection must not mutate the immutable cap ledger either.
    if state, err := h.cap.Snapshot(h.ctx); err != nil ||
        state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
        t.Fatalf("repeated rejection changed issuance: %+v, %v", state, err)
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
    // Confirm the repaired fixture actually restored both denominations before
    // accepting a successful reconciliation; counters alone are insufficient.
    if got := h.bank.GetBalance(h.ctx, addr, BaseDenom).Amount.String(); got != MaxBase {
        t.Fatalf("native balance not restored: got %s, want %s", got, MaxBase)
    }
    if got := h.bank.GetBalance(h.ctx, addr, "uother").Amount.String(); got != "50" {
        t.Fatalf("unrelated balance not restored: got %s, want 50", got)
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
    // Repeated reconciliation of repaired balances must be idempotent.
    if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
        t.Fatalf("second reconciliation of repaired balances rejected: %v", err)
    }
    if state, err := h.cap.Snapshot(h.ctx); err != nil ||
        state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
        t.Fatalf("repeated recovery changed immutable issuance: %+v, %v", state, err)
    }
    // A previously successful recovery must not permanently disable future
    // discrepancy detection. Reintroduce a native deficit after recovery.
    if err := h.bank.UncheckedSetBalance(h.ctx, addr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(less))); err != nil {
        t.Fatalf("could not reintroduce native deficit after recovery: %v", err)
    }
    if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
        t.Fatalf("reconciliation accepted new deficit after successful recovery: %v", err)
    }
    if state, err := h.cap.Snapshot(h.ctx); err != nil ||
        state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
        t.Fatalf("post-recovery deficit changed immutable issuance: %+v, %v", state, err)
    }
    // A renewed supply discrepancy must not permit native issuance while
    // the bank and immutable cap ledger disagree.
    if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
        t.Fatalf("native mint allowed during post-recovery deficit: %v", err)
    }
    if err := h.bank.UncheckedSetBalance(h.ctx, addr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max))); err != nil {
        t.Fatalf("could not restore post-recovery deficit: %v", err)
    }
    if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
        t.Fatalf("second restoration rejected: %v", err)
    }
    // The second recovery must restore the real account balance and leave
    // both declared supplies and the immutable issuance ledger untouched.
    if got := h.bank.GetBalance(h.ctx, addr, BaseDenom).Amount.String(); got != MaxBase {
        t.Fatalf("second recovery left native balance incorrect: %s", got)
    }
    if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != MaxBase {
        t.Fatalf("second recovery changed declared native supply: %s", got)
    }
    if state, err := h.cap.Snapshot(h.ctx); err != nil ||
        state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
        t.Fatalf("second recovery changed immutable issuance: %+v, %v", state, err)
    }
    // A second native-only repair must leave the unrelated denomination intact.
    if got := h.bank.GetBalance(h.ctx, addr, "uother").Amount.String(); got != "50" {
        t.Fatalf("second recovery changed unrelated account balance: %s", got)
    }
    if got := h.bank.GetSupply(h.ctx, "uother").Amount.String(); got != "50" {
        t.Fatalf("second recovery changed unrelated declared supply: %s", got)
    }
    // Recovery must not silently re-enable minting at the exact cap.
    if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
        t.Fatalf("recovery re-enabled native minting: %v", err)
    }
}


// An unrelated-denomination deficit cannot cancel an untracked native surplus.
// This is the opposite direction of the native-deficit regression above.
func TestActualSDKBankExactCapNativeSurplusCrossDenomFailsClosed(t *testing.T) {
    h := newRealBankHarness(t)
    max, ok := new(big.Int).SetString(MaxBase, 10)
    if !ok {
        t.Fatal("invalid embedded native PRVI maximum")
    }
    addr := authtypes.NewModuleAddress("exactcapsurplus")
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
    more := new(big.Int).Add(max, big.NewInt(1))
    if err := h.bank.UncheckedSetBalance(h.ctx, addr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(more))); err != nil {
        t.Fatalf("could not construct native surplus: %v", err)
    }
    if err := h.bank.UncheckedSetBalance(h.ctx, addr, sdk.NewInt64Coin("uother", 49)); err != nil {
        t.Fatalf("could not construct unrelated deficit: %v", err)
    }
    // Ensure both unchecked bank writes took effect before testing rejection.
    // Otherwise a passing reconciliation assertion could hide a broken fixture.
    if got := h.bank.GetBalance(h.ctx, addr, BaseDenom).Amount.String(); got != more.String() {
        t.Fatalf("native surplus fixture missing: got %s, want %s", got, more.String())
    }
    if got := h.bank.GetBalance(h.ctx, addr, "uother").Amount.String(); got != "49" {
        t.Fatalf("unrelated deficit fixture missing: got %s, want 49", got)
    }
    if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != MaxBase {
        t.Fatalf("declared native supply changed: %s", got)
    }
    if got := h.bank.GetSupply(h.ctx, "uother").Amount.String(); got != "50" {
        t.Fatalf("declared unrelated supply changed: %s", got)
    }
    if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
        t.Fatalf("unrelated deficit concealed native surplus: %v", err)
    }
    if state, err := h.cap.Snapshot(h.ctx); err != nil ||
        state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
        t.Fatalf("rejected surplus changed immutable issuance: %+v, %v", state, err)
    }
    if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
        t.Fatalf("native mint allowed with untracked surplus: %v", err)
    }
    // A rejected surplus must not silently alter the corrupted account balances.
    if got := h.bank.GetBalance(h.ctx, addr, BaseDenom).Amount.String(); got != more.String() {
        t.Fatalf("rejected surplus modified native account balance: got %s, want %s", got, more.String())
    }
    if got := h.bank.GetBalance(h.ctx, addr, "uother").Amount.String(); got != "49" {
        t.Fatalf("rejected surplus modified unrelated account balance: got %s, want 49", got)
    }
    if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
        t.Fatalf("repeated reconciliation accepted unresolved native surplus: %v", err)
    }
    if err := h.bank.UncheckedSetBalance(h.ctx, addr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max))); err != nil {
        t.Fatalf("could not restore native balance: %v", err)
    }
    if err := h.bank.UncheckedSetBalance(h.ctx, addr, sdk.NewInt64Coin("uother", 50)); err != nil {
        t.Fatalf("could not restore unrelated balance: %v", err)
    }
    if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
        t.Fatalf("repaired balances rejected: %v", err)
    }
    // Successful repair must preserve both declared bank supplies and the
    // immutable native issuance record, not merely return nil.
    if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != MaxBase {
        t.Fatalf("surplus recovery changed declared native supply: %s", got)
    }
    if got := h.bank.GetSupply(h.ctx, "uother").Amount.String(); got != "50" {
        t.Fatalf("surplus recovery changed unrelated declared supply: %s", got)
    }
    if state, err := h.cap.Snapshot(h.ctx); err != nil ||
        state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
        t.Fatalf("surplus recovery changed immutable issuance: %+v, %v", state, err)
    }
    // Repair of an untracked native surplus must not restore mint authority.
    if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
        t.Fatalf("surplus recovery re-enabled native minting: %v", err)
    }
}
