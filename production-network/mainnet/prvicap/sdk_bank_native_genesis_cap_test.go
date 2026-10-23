package prvicap

// Copyright (c) 2026 Privi World Corp. Isolated SDK test-only genesis cases.
// These tests only run when the pinned SDK source patch is active; no coins
// are minted, signed, issued, or deployed to a public/financial chain.
import (
  "bytes"
  "fmt"
  "math/big"
  "os"
  "strings"
  "testing"

  sdkmath "cosmossdk.io/math"
  sdk "github.com/cosmos/cosmos-sdk/types"
  banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
)

func TestSDKPatchedNativeGenesisOneBillionCap(t *testing.T) {
  if os.Getenv("PRVI_TEST_SDK_BANK_OVERLAY") != "1" {
    t.Skip("requires exact pinned Cosmos SDK bank hardening")
  }

  capUnits := new(big.Int).Exp(big.NewInt(10),big.NewInt(27),nil)
  sender := sdk.AccAddress(bytes.Repeat([]byte{0x81},20))
  newNative := func(base *big.Int) sdk.Coins {
    return sdk.NewCoins(sdk.NewCoin(BaseDenom,sdkmath.NewIntFromBigInt(base)))
  }

  for _,tc := range []struct{
    name string
    declared *big.Int
    allocated *big.Int
    wantPanic string
  }{
    {"one-base-unit-over-cap",new(big.Int).Add(capUnits,big.NewInt(1)),
      new(big.Int).Add(capUnits,big.NewInt(1)),"native genesis supply above hard cap"},
    {"balances-over-cap-even-if-declared-at-cap",new(big.Int).Set(capUnits),
      new(big.Int).Add(capUnits,big.NewInt(1)),"native genesis balances above hard cap"},
    {"underdeclared-native-supply",big.NewInt(99),big.NewInt(100),
      "native genesis supply does not match balances"},
    {"overdeclared-native-supply",big.NewInt(101),big.NewInt(100),
      "native genesis supply does not match balances"},
    {"exact-one-billion-native-PRVI-cap",new(big.Int).Set(capUnits),
      new(big.Int).Set(capUnits),""},
  }{
    t.Run(tc.name,func(t *testing.T){
      h := newRealBankHarness(t)
      balances := []banktypes.Balance{
        {Address:sender.String(),Coins:newNative(tc.allocated)},
      }
      genesis := &banktypes.GenesisState{
        Params:banktypes.DefaultParams(),
        Balances:balances,
        Supply:newNative(tc.declared),
      }
      if tc.wantPanic != "" {
        func(){
          defer func(){
            r:=recover()
            if r==nil || !strings.Contains(fmt.Sprint(r),tc.wantPanic) {
              t.Fatalf("unexpected bad genesis result: %v (want %q)",r,tc.wantPanic)
            }
          }()
          h.bank.InitGenesis(h.ctx,genesis)
        }()
        if got:=h.bank.GetSupply(h.ctx,BaseDenom).Amount;got.IsPositive() {
          t.Fatalf("failed genesis incorrectly wrote native supply: %s",got)
        }
        if got:=h.bank.GetBalance(h.ctx,sender,BaseDenom).Amount;got.IsPositive(){
          t.Fatalf("failed genesis incorrectly wrote native balance: %s",got)
        }
        return
      }
      // This is a disposable in-memory SDK store, NOT a real financial
      // genesis. A full, exact-cap amount must fit arbitrary-precision Int.
      h.bank.InitGenesis(h.ctx,genesis)
      if got:=h.bank.GetSupply(h.ctx,BaseDenom).Amount.BigInt();got.Cmp(capUnits)!=0{
        t.Fatalf("accepted exact-cap supply differs: %s",got)
      }
      if got:=h.bank.GetBalance(h.ctx,sender,BaseDenom).Amount.BigInt();got.Cmp(capUnits)!=0{
        t.Fatalf("accepted exact-cap balance differs: %s",got)
      }
    })
  }
}
