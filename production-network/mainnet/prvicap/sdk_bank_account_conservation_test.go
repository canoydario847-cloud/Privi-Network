package prvicap

import (
  "bytes"
  "errors"
  "testing"

  sdk "github.com/cosmos/cosmos-sdk/types"
)

// A raw SDK BaseKeeper can change account records without updating its
// declared Supply metadata. Native account-balance conservation must detect
// that mismatch, even though the supply number is still below the hard cap.
// These tests are defensive detection, not complete prevention.
func TestNativeAccountConservationDetectsRawKeeperMismatch(t *testing.T) {
  h := newRealBankHarness(t)
  h.genesisFund(t, 100)
  if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil { t.Fatal(err) }
  guarded := RestrictedBank(h.bank, h.cap)
  receiver := sdk.AccAddress(bytes.Repeat([]byte{0x51}, 20))
  if err := h.bank.UncheckedSetBalance(h.ctx, receiver, sdk.NewInt64Coin(BaseDenom, 1)); err != nil {
    t.Fatalf("setting untracked raw balance to demonstrate a bypass: %v", err)
  }
  if got := guarded.GetSupply(h.ctx, BaseDenom).Amount.String(); got != "100" {
    t.Fatalf("expected declared supply to remain unchanged, got %s", got)
  }
  if err := h.cap.Reconcile(h.ctx, guarded); !errors.Is(err, ErrUnexpectedSupply) {
    t.Fatalf("account conservation failed to catch untracked raw balance change: %v", err)
  }
}

func TestNativeGenesisRejectsUndeclaredBankAccountBeforeCapWrite(t *testing.T) {
  h := newRealBankHarness(t)
  h.genesisFund(t, 100)
  receiver := sdk.AccAddress(bytes.Repeat([]byte{0x52}, 20))
  if err := h.bank.UncheckedSetBalance(h.ctx, receiver, sdk.NewInt64Coin(BaseDenom, 1)); err != nil {
    t.Fatalf("untracked bank state fixture: %v", err)
  }
  if err := h.cap.InitGenesis(h.ctx, "100", h.bank); !errors.Is(err, ErrBankSupplyMismatch) {
    t.Fatalf("expected unchecked native balance change to deny genesis: %v", err)
  }
  if _, err := h.cap.Snapshot(h.ctx); !errors.Is(err, ErrNotInitialized) {
    t.Fatalf("cap state was written despite rejected genesis: %v", err)
  }
}

func TestValidNativeAccountConservationPasses(t *testing.T) {
  h := newRealBankHarness(t)
  h.genesisFund(t, 100)
  if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil { t.Fatal(err) }
  if err := h.cap.Reconcile(h.ctx, RestrictedBank(h.bank, h.cap)); err != nil {
    t.Fatalf("legitimate bank state must reconcile: %v", err)
  }
}
