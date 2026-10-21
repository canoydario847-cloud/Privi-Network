package prvicap

import (
    "bytes"
    "errors"
    "testing"

    sdk "github.com/cosmos/cosmos-sdk/types"
    bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
)

func TestModuleUnsafeNativeSetterDeniedWithoutBankMutation(t *testing.T) {
    h := newRealBankHarness(t)
    h.genesisFund(t, 100)
    if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil { t.Fatal(err) }
    guarded := RestrictedBank(h.bank, h.cap)
    recipient := sdk.AccAddress(bytes.Repeat([]byte{0x43}, 20))
    if err := guarded.UncheckedSetBalance(h.ctx, recipient, sdk.NewInt64Coin(BaseDenom, 1)); !errors.Is(err, ErrDirectNativeBalanceForbidden) {
        t.Fatalf("unchecked native write must be denied, got %v", err)
    }
    if got := guarded.GetBalance(h.ctx, recipient, BaseDenom).Amount.Int64(); got != 0 {
        t.Fatalf("denied setter changed bank account by %d", got)
    }
    if got := guarded.GetSupply(h.ctx, BaseDenom).Amount.String(); got != "100" {
        t.Fatalf("denied setter changed native supply: %s", got)
    }
    if err := h.cap.Reconcile(h.ctx, guarded); err != nil { t.Fatal(err) }
}

func TestNativeNoOpAllowsVMInitializationWithoutWrite(t *testing.T) {
    h := newRealBankHarness(t)
    h.genesisFund(t, 100)
    if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil { t.Fatal(err) }
    guarded := RestrictedBank(h.bank, h.cap)
    account := sdk.AccAddress(bytes.Repeat([]byte{0x44}, 20))
    if err := guarded.UncheckedSetBalance(h.ctx, account, sdk.NewInt64Coin(BaseDenom, 0)); err != nil {
        t.Fatalf("native zero-balance no-op should be permitted: %v", err)
    }
    module := sdk.AccAddress(bytes.Repeat([]byte{0x41}, 20))
    unchanged := guarded.GetBalance(h.ctx, module, BaseDenom)
    if err := guarded.UncheckedSetBalance(h.ctx, module, unchanged); err != nil {
        t.Fatalf("native idempotent setter should not write: %v", err)
    }
    if err := guarded.UncheckedSetBalance(h.ctx, module, sdk.NewInt64Coin(BaseDenom, 2)); !errors.Is(err, ErrDirectNativeBalanceForbidden) {
        t.Fatalf("non-idempotent setter slipped through: %v", err)
    }
    if err := h.cap.Reconcile(h.ctx, guarded); err != nil { t.Fatal(err) }
}

func TestUnrelatedTestAssetSetterUnchanged(t *testing.T) {
    h := newRealBankHarness(t)
    h.genesisFund(t, 100)
    if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil { t.Fatal(err) }
    guarded := RestrictedBank(h.bank, h.cap)
    account := sdk.AccAddress(bytes.Repeat([]byte{0x45}, 20))
    if err := guarded.UncheckedSetBalance(h.ctx, account, sdk.NewInt64Coin("atest", 5)); err != nil {
        t.Fatalf("non-native dev asset unexpectedly denied: %v", err)
    }
    if got := guarded.GetBalance(h.ctx, account, "atest").Amount.String(); got != "5" {
        t.Fatalf("unrelated asset setter failed: %s", got)
    }
    if err := h.cap.Reconcile(h.ctx, guarded); err != nil { t.Fatal(err) }
}

func TestModuleBankCannotDeriveUnrestrictedBuilderCopy(t *testing.T) {
    h := newRealBankHarness(t)
    guarded := RestrictedBank(h.bank, h.cap)
    if _, ok := any(guarded).(bankkeeper.BaseKeeper); ok {
        t.Fatal("module-facing bank must not be a concrete BaseKeeper")
    }
    t.Run("mint restriction", func(t *testing.T) {
        defer func() { if recover() == nil { t.Fatal("WithMintCoinsRestriction leaked keeper") } }()
        _ = guarded.WithMintCoinsRestriction(nil)
    })
    t.Run("object store", func(t *testing.T) {
        defer func() { if recover() == nil { t.Fatal("WithObjStoreKey leaked keeper") } }()
        _ = guarded.WithObjStoreKey(nil)
    })
}

// A raw keeper intentionally remains able to bypass the wrapper, so native
// banking is NOT independently audited or ready for financial mainnet. The
// old BaseKeeper instance must not reach any non-bank SDK module.
func TestRawBankKeeperBypassStillRequiresSeparateFix(t *testing.T) {
    h := newRealBankHarness(t)
    h.genesisFund(t, 100)
    if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil { t.Fatal(err) }
    guarded := RestrictedBank(h.bank, h.cap)
    account := sdk.AccAddress(bytes.Repeat([]byte{0x46}, 20))
    if err := guarded.UncheckedSetBalance(h.ctx, account, sdk.NewInt64Coin(BaseDenom, 1)); !errors.Is(err, ErrDirectNativeBalanceForbidden) {
        t.Fatalf("guard missing: %v", err)
    }
    if err := h.bank.UncheckedSetBalance(h.ctx, account, sdk.NewInt64Coin(BaseDenom, 1)); err != nil {
        t.Fatalf("failed to demonstrate residual raw keeper bypass: %v", err)
    }
    // The raw setter can change native balances without updating declared
    // bank supply. This is more dangerous than mere over-cap minting; it
    // needs a module/SDK-level provenance audit, not just Reconcile().
    if got := guarded.GetBalance(h.ctx, account, BaseDenom).Amount.String(); got != "1" {
        t.Fatalf("raw keeper attack was not observable: %s", got)
    }
}
