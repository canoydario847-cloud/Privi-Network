package prvicap

import (
 "bytes"
 "os"
 "testing"

 sdk "github.com/cosmos/cosmos-sdk/types"
 authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
 banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
 "go.uber.org/mock/gomock"
)

// This test MUST only run when Go -overlay swaps in the exact pinned Cosmos
// SDK v0.54.3 bank source. It is skipped on vanilla SDK to preserve the
// separate test that demonstrates the raw BaseKeeper bypass.
func TestSDKPatchedNativeBankSourceEnforcement(t *testing.T) {
 if os.Getenv("PRVI_TEST_SDK_BANK_OVERLAY") != "1" { t.Skip("requires explicit pinned SDK source overlay") }
 h:=newRealBankHarness(t)
 receiver:=sdk.AccAddress(bytes.Repeat([]byte{0x65},20))
 if err:=h.bank.UncheckedSetBalance(h.ctx,receiver,sdk.NewInt64Coin(BaseDenom,1)); err==nil {
   t.Fatal("raw SDK external native setter still writes untracked aprvi")
 }
 if h.bank.GetBalance(h.ctx,receiver,BaseDenom).Amount.IsPositive() {
   t.Fatal("rejected raw setter changed native balance")
 }
 if err:=h.bank.MintCoins(h.ctx,"unrestricted-raw-copy",sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1)));err==nil {
   t.Fatal("unrestricted raw SDK BaseKeeper still mints native aprvi")
 }
 if h.bank.GetSupply(h.ctx,BaseDenom).Amount.IsPositive() {
   t.Fatal("denied raw native mint altered supply")
 }
 if err:=h.bank.UncheckedSetBalance(h.ctx,receiver,sdk.NewInt64Coin(BaseDenom,0));err!=nil {
   t.Fatalf("unchanged native zero balance should be a no-write: %v",err)
 }
 if err:=h.bank.UncheckedSetBalance(h.ctx,receiver,sdk.NewInt64Coin("atest",2));err!=nil {
   t.Fatalf("non-native SDK raw setter should preserve current behavior: %v",err)
 }
 if got:=h.bank.GetBalance(h.ctx,receiver,"atest").Amount.Int64();got!=2 {
   t.Fatalf("unrelated asset unexpectedly changed: %d",got)
 }
}

func TestSDKPatchedBankGenesisAndLegitimateNativeTransfer(t *testing.T) {
 if os.Getenv("PRVI_TEST_SDK_BANK_OVERLAY") != "1" { t.Skip("requires pinned SDK bank source overlay") }
 h:=newRealBankHarness(t)
 sender:=sdk.AccAddress(bytes.Repeat([]byte{0x71},20))
 receiver:=sdk.AccAddress(bytes.Repeat([]byte{0x72},20))
 native:=sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,100))
 // SDK InitGenesis writes audited initial bank allocations directly. New
 // issuance remains forbidden afterwards by the modified raw MintCoins.
 h.bank.InitGenesis(h.ctx,&banktypes.GenesisState{
   Params:banktypes.DefaultParams(),
   Balances:[]banktypes.Balance{{Address:sender.String(),Coins:native}},
   Supply:native,
 })
 if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil {t.Fatal(err)}
 // Bank's normal internal transfer must still write the actual native
 // balance collections, unlike the external UncheckedSetBalance entry.
 // This fixture starts with no recipient account: the SDK must create it.
 h.account.EXPECT().HasAccount(h.ctx,receiver).Return(false).Times(1)
 h.account.EXPECT().GetAccount(h.ctx,gomock.Any()).Return(nil).AnyTimes()
 h.account.EXPECT().NewAccountWithAddress(h.ctx,receiver).
   Return(authtypes.NewBaseAccountWithAddress(receiver)).AnyTimes()
 h.account.EXPECT().SetAccount(h.ctx,gomock.Any()).AnyTimes()
 if err:=h.bank.SendCoins(h.ctx,sender,receiver,sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,25)));err!=nil {
   t.Fatalf("patched SDK blocked legitimate native transfer: %v",err)
 }
 if got:=h.bank.GetBalance(h.ctx,sender,BaseDenom).Amount.Int64();got!=75 {
   t.Fatalf("sender native balance = %d, want 75",got)
 }
 if got:=h.bank.GetBalance(h.ctx,receiver,BaseDenom).Amount.Int64();got!=25 {
   t.Fatalf("recipient native balance = %d, want 25",got)
 }
 if err:=h.cap.Reconcile(h.ctx,h.bank);err!=nil {
   t.Fatalf("legitimate transfer violated native conservation: %v",err)
 }
 // Rejected raw writes must be atomic: neither inflationary credits nor
 // unauthorized debits may alter a funded account or the bank's supply.
 for _,tc:=range []struct{
   name string
   address sdk.AccAddress
   balance int64
 }{
   {"receiver-credit",receiver,26},
   {"receiver-debit",receiver,24},
   {"receiver-drain",receiver,0},
   {"sender-credit",sender,76},
   {"sender-debit",sender,74},
   {"sender-drain",sender,0},
 } {
   t.Run(tc.name,func(t *testing.T) {
     if err:=h.bank.UncheckedSetBalance(h.ctx,tc.address,sdk.NewInt64Coin(BaseDenom,tc.balance));err==nil {
       t.Fatal("raw caller altered a funded native PRVI balance")
     }
     if got:=h.bank.GetBalance(h.ctx,sender,BaseDenom).Amount.Int64();got!=75 {
       t.Fatalf("rejected raw write changed sender balance to %d",got)
     }
     if got:=h.bank.GetBalance(h.ctx,receiver,BaseDenom).Amount.Int64();got!=25 {
       t.Fatalf("rejected raw write changed receiver balance to %d",got)
     }
     if got:=h.bank.GetSupply(h.ctx,BaseDenom).Amount.Int64();got!=100 {
       t.Fatalf("rejected raw write changed native supply to %d",got)
     }
     if err:=h.cap.Reconcile(h.ctx,h.bank);err!=nil {
       t.Fatalf("native accounting failed after rejected raw write: %v",err)
     }
   })
 }
}


// A legitimate native burn decreases outstanding supply, but must never
// authorize replacement issuance. Both the SDK raw keeper and consensus cap
// must continue to deny any post-genesis aprvi mint (zero inflation).
func TestSDKPatchedNativeBurnCannotReopenMintBudget(t *testing.T) {
 if os.Getenv("PRVI_TEST_SDK_BANK_OVERLAY") != "1" { t.Skip("requires pinned SDK bank source overlay") }
 h:=newRealBankHarness(t)
 burner:=authtypes.NewEmptyModuleAccount("burnfixture",authtypes.Burner)
 native:=sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,100))
 h.bank.InitGenesis(h.ctx,&banktypes.GenesisState{
   Params:banktypes.DefaultParams(),
   Balances:[]banktypes.Balance{{Address:burner.GetAddress().String(),Coins:native}},
   Supply:native,
 })
 if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil {t.Fatal(err)}
 h.account.EXPECT().GetModuleAccount(h.ctx,"burnfixture").Return(burner)
 // SDK v0.54.3 LockedCoins checks the burner account before debiting.
 // Keep this expectation address-specific so an unrelated account lookup fails.
 h.account.EXPECT().GetAccount(h.ctx,burner.GetAddress()).Return(burner).MinTimes(1)
 if err:=h.bank.BurnCoins(h.ctx,"burnfixture",sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,40)));err!=nil {
   t.Fatalf("legitimate native burn rejected: %v",err)
 }
 if got:=h.bank.GetSupply(h.ctx,BaseDenom).Amount.Int64();got!=60 {
   t.Fatalf("burn did not reduce outstanding native supply: %d",got)
 }
 if got:=h.bank.GetBalance(h.ctx,burner.GetAddress(),BaseDenom).Amount.Int64();got!=60 {
   t.Fatalf("burner native balance did not decrease: %d",got)
 }
 if err:=h.cap.Reconcile(h.ctx,h.bank);err!=nil {t.Fatalf("burn violated conservation: %v",err)}
 if err:=h.bank.MintCoins(h.ctx,"unrestricted-raw-copy",sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,40)));err==nil {
   t.Fatal("raw keeper re-minted previously burned native PRVI")
 }
 if got:=h.bank.GetSupply(h.ctx,BaseDenom).Amount.Int64();got!=60 {
   t.Fatalf("denied remint changed outstanding supply: %d",got)
 }
 if err:=h.cap.Reconcile(h.ctx,h.bank);err!=nil {t.Fatalf("denied remint violated conservation: %v",err)}
 snapshot,err:=h.cap.Snapshot(h.ctx)
 if err!=nil {t.Fatal(err)}
 if snapshot.GenesisBase!="100" || snapshot.LifetimeIssuedBase!="100" {
   t.Fatalf("burn improperly reopened immutable issuance: %+v",snapshot)
 }
}

// Reject a mixed-denomination raw mint before *either* native or unrelated
// bank state can change; do not allow a valid test asset to mask aprvi.
func TestSDKPatchedMixedNativeMintIsAtomic(t *testing.T) {
 if os.Getenv("PRVI_TEST_SDK_BANK_OVERLAY") != "1" { t.Skip("requires pinned SDK bank source overlay") }
 h:=newRealBankHarness(t)
 amounts:=sdk.NewCoins(sdk.NewInt64Coin("aprvi",1),sdk.NewInt64Coin("atest",9))
 if err:=h.bank.MintCoins(h.ctx,"unrestricted-raw-copy",amounts);err==nil {
   t.Fatal("mixed native+foreign raw mint unexpectedly succeeded")
 }
 for _,denom:=range []string{BaseDenom,"atest"} {
   if got:=h.bank.GetSupply(h.ctx,denom).Amount;got.IsPositive() {
     t.Fatalf("rejected mixed mint partially changed %s supply: %s",denom,got)
   }
 }
}
