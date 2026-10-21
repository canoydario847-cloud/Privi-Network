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
 h.account.EXPECT().GetAccount(h.ctx,receiver).Return(nil).AnyTimes()
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
 if err:=h.bank.UncheckedSetBalance(h.ctx,receiver,sdk.NewInt64Coin(BaseDenom,26));err==nil {
   t.Fatal("raw caller changed native balance after legitimate transfer")
 }
}
