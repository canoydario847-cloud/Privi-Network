package keeper_test

// Compiled only into a disposable copied Cosmos SDK v0.54.3 source tree.
// Exercises the concrete SDK keeper, its real bank collection store and
// public unchecked setter. No real production keys, chain or tokens.
import (
    "bytes"
    "strings"
    "testing"

    "cosmossdk.io/log/v2"
    "go.uber.org/mock/gomock"
    "github.com/cosmos/cosmos-sdk/codec/address"
    "github.com/cosmos/cosmos-sdk/runtime"
    storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
    "github.com/cosmos/cosmos-sdk/testutil"
    sdk "github.com/cosmos/cosmos-sdk/types"
    moduletestutil "github.com/cosmos/cosmos-sdk/types/module/testutil"
    authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
    bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
    banktestutil "github.com/cosmos/cosmos-sdk/x/bank/testutil"
    banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
    govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
)

func TestPriviNativeDirectSetterDeniedWithConcreteBaseKeeper(t *testing.T) {
    key:=storetypes.NewKVStoreKey(banktypes.StoreKey)
    objKey:=storetypes.NewObjectStoreKey(banktypes.ObjectStoreKey)
    testCtx:=testutil.DefaultContextWithObjectStore(t,key,
        storetypes.NewTransientStoreKey("transient_test"),objKey)
    ctx:=testCtx.Ctx
    ctrl:=gomock.NewController(t)
    ak:=banktestutil.NewMockAccountKeeper(ctrl)
    ak.EXPECT().AddressCodec().Return(address.NewBech32Codec("cosmos")).AnyTimes()
    cfg:=moduletestutil.MakeTestEncodingConfig()
    k:=bankkeeper.NewBaseKeeper(cfg.Codec,runtime.NewKVStoreService(key),ak,
        map[string]bool{},authtypes.NewModuleAddress(govtypes.ModuleName).String(),
        log.NewNopLogger()).WithObjStoreKey(objKey)
    minter:=authtypes.NewEmptyModuleAccount("genesisfixture",authtypes.Minter)
    src:=minter.GetAddress()
    dst:=sdk.AccAddress(bytes.Repeat([]byte{0x33},20))

    // An idempotent zero write is necessary for EVM precompile genesis.
    if err:=k.UncheckedSetBalance(ctx,src,sdk.NewInt64Coin("aprvi",0));err!=nil {
        t.Fatalf("zero->zero assertion should be a no-op: %v",err)
    }
    // This protected package-only balance mutation represents reviewed
    // upstream bank internal transfer/mint logic, NOT a public SDK API.
    ak.EXPECT().GetModuleAccount(ctx,"genesisfixture").Return(minter)
    if err:=k.MintCoins(ctx,"genesisfixture",sdk.NewCoins(sdk.NewInt64Coin("aprvi",100)));err!=nil {
        t.Fatal(err)
    }
    if err:=k.UncheckedSetBalance(ctx,src,sdk.NewInt64Coin("aprvi",100));err!=nil {
        t.Fatalf("unchanged native account assertion denied: %v",err)
    }
    for _,amount:=range []int64{0,1,99,101} {
        err:=k.UncheckedSetBalance(ctx,src,sdk.NewInt64Coin("aprvi",amount))
        if err==nil || !strings.Contains(err.Error(),
             "PRVI forbidden direct unchecked native account balance write") {
            t.Fatalf("direct native change to %d not rejected: %v",amount,err)
        }
    }
    if got:=k.GetBalance(ctx,src,"aprvi").Amount.Int64();got!=100 {
        t.Fatalf("denied setter mutated sender: %d",got)
    }
    // Legitimate bank transfers use private bank internals after this patch,
    // rather than the public unchecked setter. Preserve ordinary send behavior.
    ak.EXPECT().GetAccount(ctx,src).Return(minter)
    ak.EXPECT().HasAccount(ctx,dst).Return(true)
    if err:=k.SendCoins(ctx,src,dst,sdk.NewCoins(sdk.NewInt64Coin("aprvi",1)));err!=nil {
        t.Fatalf("legitimate SDK native send failed: %v",err)
    }
    if k.GetBalance(ctx,src,"aprvi").Amount.Int64()!=99 ||
        k.GetBalance(ctx,dst,"aprvi").Amount.Int64()!=1 {
        t.Fatalf("bank send should conserve account totals (99,1)")
    }
    // The raw public setter is still allowed for distinct, nonnative denoms.
    if err:=k.UncheckedSetBalance(ctx,dst,sdk.NewInt64Coin("atest",5));err!=nil {
        t.Fatalf("unrelated TEST denomination must remain untouched: %v",err)
    }
}

func TestPriviConcreteBankTypeUnchanged(t *testing.T) {
    var _ bankkeeper.SendKeeper = bankkeeper.BaseSendKeeper{}
    var _ bankkeeper.Keeper = bankkeeper.BaseKeeper{}
}
