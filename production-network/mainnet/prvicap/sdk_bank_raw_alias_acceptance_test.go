package prvicap

import (
    "bytes"
    "errors"
    "testing"

    sdk "github.com/cosmos/cosmos-sdk/types"
    authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
)

// These are RED acceptance tests for issue #250, not evidence that the
// current SDK adapter is safe. The raw BaseKeeper in bankHarness deliberately
// retains the capabilities that the module-facing wrapper cannot revoke.
// Do not merge or enable financial mainnet while these assertions fail.
//
// The eventual production fix must make denial happen before any consensus
// write, regardless of which keeper alias, SDK module or migration calls it.
// These tests cover the raw-alias failure at the bank boundary only; a
// production-app-linked matrix and restart/commit tests are still required.

func TestAcceptanceRawKeeperAliasCannotMintNativePRVI(t *testing.T) {
    h := newRealBankHarness(t)
    h.genesisFund(t, 100)
    if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil {
        t.Fatal(err)
    }

    minter := authtypes.NewEmptyModuleAccount("rawalias", authtypes.Minter)
    h.account.EXPECT().GetModuleAccount(h.ctx, "rawalias").Return(minter).AnyTimes()

    beforeSupply := h.bank.GetSupply(h.ctx, BaseDenom)
    beforeBalance := h.bank.GetBalance(h.ctx, minter.GetAddress(), BaseDenom)
    beforeCap, err := h.cap.Snapshot(h.ctx)
    if err != nil { t.Fatal(err) }

    // Required invariant: a retained raw keeper must fail just like the
    // module-facing wrapper. On current main, this call incorrectly succeeds.
    mintErr := h.bank.MintCoins(h.ctx, "rawalias",
        sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1)))
    if !errors.Is(mintErr, ErrMintForbidden) {
        t.Errorf("NO-GO: raw keeper issued native PRVI; want pre-write denial, got %v", mintErr)
    }
    if got := h.bank.GetSupply(h.ctx, BaseDenom); !got.IsEqual(beforeSupply) {
        t.Errorf("NO-GO: rejected mint changed native supply: before=%s after=%s", beforeSupply, got)
    }
    if got := h.bank.GetBalance(h.ctx, minter.GetAddress(), BaseDenom); !got.IsEqual(beforeBalance) {
        t.Errorf("NO-GO: rejected mint changed module account: before=%s after=%s", beforeBalance, got)
    }
    afterCap, err := h.cap.Snapshot(h.ctx)
    if err != nil { t.Fatal(err) }
    if afterCap != beforeCap {
        t.Errorf("NO-GO: rejected mint changed lifetime cap record: before=%+v after=%+v", beforeCap, afterCap)
    }
}

func TestAcceptanceRawKeeperAliasCannotWriteNativeBalance(t *testing.T) {
    h := newRealBankHarness(t)
    h.genesisFund(t, 100)
    if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil {
        t.Fatal(err)
    }

    recipient := sdk.AccAddress(bytes.Repeat([]byte{0x61}, 20))
    beforeSupply := h.bank.GetSupply(h.ctx, BaseDenom)
    beforeBalance := h.bank.GetBalance(h.ctx, recipient, BaseDenom)
    beforeCap, err := h.cap.Snapshot(h.ctx)
    if err != nil { t.Fatal(err) }

    // An unsafe setter must not create native balance outside bank accounting.
    // Supply-only reconciliation misses this until an account-sum scan.
    writeErr := h.bank.UncheckedSetBalance(h.ctx, recipient,
        sdk.NewInt64Coin(BaseDenom, 1))
    if !errors.Is(writeErr, ErrDirectNativeBalanceForbidden) {
        t.Errorf("NO-GO: raw keeper wrote native balance; want pre-write denial, got %v", writeErr)
    }
    if got := h.bank.GetBalance(h.ctx, recipient, BaseDenom); !got.IsEqual(beforeBalance) {
        t.Errorf("NO-GO: rejected unsafe setter changed native balance: before=%s after=%s", beforeBalance, got)
    }
    if got := h.bank.GetSupply(h.ctx, BaseDenom); !got.IsEqual(beforeSupply) {
        t.Errorf("NO-GO: rejected unsafe setter changed native supply: before=%s after=%s", beforeSupply, got)
    }
    afterCap, err := h.cap.Snapshot(h.ctx)
    if err != nil { t.Fatal(err) }
    if afterCap != beforeCap {
        t.Errorf("NO-GO: rejected unsafe setter changed lifetime cap record: before=%+v after=%+v", beforeCap, afterCap)
    }
}

func TestAcceptanceRawKeeperNativeMixedDenomMintIsAtomic(t *testing.T) {
    h := newRealBankHarness(t)
    h.genesisFund(t, 100)
    if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil {
        t.Fatal(err)
    }

    minter := authtypes.NewEmptyModuleAccount("mixedalias", authtypes.Minter)
    h.account.EXPECT().GetModuleAccount(h.ctx, "mixedalias").Return(minter).AnyTimes()
    beforeNative := h.bank.GetSupply(h.ctx, BaseDenom)
    beforeOther := h.bank.GetSupply(h.ctx, "atest")
    beforeAccount := h.bank.GetBalance(h.ctx, minter.GetAddress(), BaseDenom)
    beforeCap, err := h.cap.Snapshot(h.ctx)
    if err != nil { t.Fatal(err) }

    mintErr := h.bank.MintCoins(h.ctx, "mixedalias", sdk.NewCoins(
        sdk.NewInt64Coin(BaseDenom, 1),
        sdk.NewInt64Coin("atest", 5),
    ))
    if !errors.Is(mintErr, ErrMintForbidden) {
        t.Errorf("NO-GO: raw mixed-denomination mint was not denied, got %v", mintErr)
    }
    if got := h.bank.GetSupply(h.ctx, BaseDenom); !got.IsEqual(beforeNative) {
        t.Errorf("NO-GO: native supply changed during denied mixed mint: %s -> %s", beforeNative, got)
    }
    if got := h.bank.GetSupply(h.ctx, "atest"); !got.IsEqual(beforeOther) {
        t.Errorf("NO-GO: other denomination changed during denied mixed mint: %s -> %s", beforeOther, got)
    }
    if got := h.bank.GetBalance(h.ctx, minter.GetAddress(), BaseDenom); !got.IsEqual(beforeAccount) {
        t.Errorf("NO-GO: module balance changed during denied mixed mint: %s -> %s", beforeAccount, got)
    }
    afterCap, err := h.cap.Snapshot(h.ctx)
    if err != nil { t.Fatal(err) }
    if afterCap != beforeCap {
        t.Errorf("NO-GO: mixed mint changed lifetime cap record: before=%+v after=%+v", beforeCap, afterCap)
    }
}
