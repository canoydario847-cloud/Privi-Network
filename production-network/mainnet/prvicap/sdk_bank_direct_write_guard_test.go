package prvicap

import (
    "bytes"
    "errors"
    "testing"

    sdk "github.com/cosmos/cosmos-sdk/types"
    authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
    banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
)

func TestAppFacingBankDeniesDirectNativeWritesButPermitsNormalSend(t *testing.T) {
    h:=newRealBankHarness(t)
    h.genesisFund(t,100)
    if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil {t.Fatal(err)}
    appBank:=BankForApp(h.bank,h.cap)
    beneficiary:=sdk.AccAddress(bytes.Repeat([]byte{0x74},20))
    minter:=authtypes.NewEmptyModuleAccount("genesisfixture",authtypes.Minter)
    // Normal SDK send consults LockedCoins and its account keeper.
    h.account.EXPECT().GetAccount(h.ctx,minter.GetAddress()).Return(minter).AnyTimes()
    for _,amount:=range []int64{0,1,50} {
        err:=appBank.UncheckedSetBalance(h.ctx,beneficiary,sdk.NewInt64Coin(BaseDenom,amount))
        if !errors.Is(err,ErrDirectNativeBalanceWriteForbidden) {
            t.Fatalf("app keeper native direct write %d bypass: %v",amount,err)
        }
    }
    if got:=appBank.GetBalance(h.ctx,beneficiary,BaseDenom).Amount.Int64();got!=0 {
        t.Fatalf("rejected direct writes changed beneficiary: %d",got)
    }
    if err:=appBank.SendCoins(h.ctx,minter.GetAddress(),beneficiary,
        sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1)));err!=nil {
        t.Fatalf("ordinary SDK bank transfer must remain valid: %v",err)
    }
    if got:=appBank.GetBalance(h.ctx,beneficiary,BaseDenom).Amount.Int64();got!=1 {
        t.Fatalf("legitimate native transfer failed: %d",got)
    }
    if got:=appBank.GetSupply(h.ctx,BaseDenom).Amount.Int64();got!=100 {
        t.Fatalf("normal transfer unexpectedly changed native supply: %d",got)
    }
    if err:=h.cap.Reconcile(h.ctx,appBank);err!=nil {
        t.Fatalf("normal authorized bank transfer must conserve native supply: %v",err)
    }
}

func TestAppFacingBankPreservesUnrelatedDenomDirectSetter(t *testing.T) {
    h:=newRealBankHarness(t)
    h.genesisFund(t,100)
    if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil {t.Fatal(err)}
    appBank:=BankForApp(h.bank,h.cap)
    address:=sdk.AccAddress(bytes.Repeat([]byte{0x2a},20))
    if err:=appBank.UncheckedSetBalance(h.ctx,address,sdk.NewInt64Coin("atest",3));err!=nil {
        t.Fatalf("unrelated disposable denom must retain SDK behavior: %v",err)
    }
    if got:=appBank.GetBalance(h.ctx,address,"atest").Amount.Int64();got!=3 {
        t.Fatalf("unrelated balance not persisted: %d",got)
    }
    if err:=h.cap.Reconcile(h.ctx,appBank);err!=nil {
        t.Fatalf("foreign denomination must not affect aprvi conservation: %v",err)
    }
}

// Explicitly document one remaining unguarded SDK API: consumers of the
// bankkeeper.Keeper interface can obtain a concrete BaseKeeper through
// WithMintCoinsRestriction/WithObjStoreKey. A peer review must remove or
// constrain such capabilities before assigning any financial value.
func TestAppBankGuardDoesNotProtectEscapedBaseKeeper(t *testing.T) {
    h:=newRealBankHarness(t)
    h.genesisFund(t,100)
    if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil {t.Fatal(err)}
    guarded:=BankForApp(h.bank,h.cap)
    copied:=guarded.WithMintCoinsRestriction(banktypes.NoOpMintingRestrictionFn)
    addr:=sdk.AccAddress(bytes.Repeat([]byte{0x37},20))
    if err:=copied.UncheckedSetBalance(h.ctx,addr,sdk.NewInt64Coin(BaseDenom,1));err!=nil {
        t.Fatalf("known unprotected SDK BaseKeeper copy behavior changed: %v",err)
    }
    if err:=h.cap.Reconcile(h.ctx,guarded);!errors.Is(err,ErrUnexpectedSupply) {
        t.Fatalf("unchecked bypass must be caught by end-block balance check: %v",err)
    }
}
