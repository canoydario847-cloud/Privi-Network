package prvicap

import (
 "errors"
 "testing"
 "time"

 dbm "github.com/cosmos/cosmos-db"
 "go.uber.org/mock/gomock"

 "cosmossdk.io/log/v2"
 "github.com/cosmos/cosmos-sdk/codec/address"
 "github.com/cosmos/cosmos-sdk/runtime"
 "github.com/cosmos/cosmos-sdk/store/v2"
 storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
 sdk "github.com/cosmos/cosmos-sdk/types"
 moduletestutil "github.com/cosmos/cosmos-sdk/types/module/testutil"
 authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
 bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
 banktestutil "github.com/cosmos/cosmos-sdk/x/bank/testutil"
 banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
 govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
 cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
)

type bankHarness struct {
 ctx sdk.Context
 bank bankkeeper.BaseKeeper
 cap Keeper
 account *banktestutil.MockAccountKeeper
 // restart commits the IAVL bank+cap stores to the database, constructs a
 // fresh multistore and a fresh cap keeper, and reopens committed chain state.
 // This is a real SDK persistence test, not the in-memory fake KV fixture.
 restart func(*testing.T) (sdk.Context, bankkeeper.BaseKeeper, Keeper)
}

func newRealBankHarness(t *testing.T) bankHarness {
 t.Helper()
 db := dbm.NewMemDB()
 cms := store.NewCommitMultiStore(db,log.NewNopLogger())
 bankKey := storetypes.NewKVStoreKey(banktypes.StoreKey)
 capKey := storetypes.NewKVStoreKey("prvicap")
 objKey := storetypes.NewObjectStoreKey(banktypes.ObjectStoreKey)
 cms.MountStoreWithDB(bankKey,storetypes.StoreTypeIAVL,db)
 cms.MountStoreWithDB(capKey,storetypes.StoreTypeIAVL,db)
 cms.MountStoreWithDB(objKey,storetypes.StoreTypeObject,db)
 if err:=cms.LoadLatestVersion();err!=nil {t.Fatal(err)}
 ctx := sdk.NewContext(cms,cmtproto.Header{Time:time.Now()},false,log.NewNopLogger())
 ctrl:=gomock.NewController(t)
 ak:=banktestutil.NewMockAccountKeeper(ctrl)
 ak.EXPECT().AddressCodec().Return(address.NewBech32Codec("cosmos")).AnyTimes()
 codec:=moduletestutil.MakeTestEncodingConfig()
 raw:=bankkeeper.NewBaseKeeper(codec.Codec,runtime.NewKVStoreService(bankKey),
   ak,map[string]bool{},authtypes.NewModuleAddress(govtypes.ModuleName).String(),log.NewNopLogger())
 raw=raw.WithObjStoreKey(objKey)
 cap,err:=New(runtime.NewKVStoreService(capKey))
 if err!=nil {t.Fatal(err)}
 restart:=func(t *testing.T) (sdk.Context,bankkeeper.BaseKeeper,Keeper) {
   t.Helper()
   // Commit before reopening to catch accidental use of a process-local
   // record that disappears when the durable SDK state is reloaded.
   cms.Commit()
   reopened:=store.NewCommitMultiStore(db,log.NewNopLogger())
   reopened.MountStoreWithDB(bankKey,storetypes.StoreTypeIAVL,db)
   reopened.MountStoreWithDB(capKey,storetypes.StoreTypeIAVL,db)
   reopened.MountStoreWithDB(objKey,storetypes.StoreTypeObject,db)
   if err:=reopened.LoadLatestVersion();err!=nil {t.Fatal(err)}
   newCtx:=sdk.NewContext(reopened,cmtproto.Header{Height:2,Time:time.Now()},false,log.NewNopLogger())
   newCap,err:=New(runtime.NewKVStoreService(capKey))
   if err!=nil {t.Fatal(err)}
   // Recreate a fresh restriction-bearing bank keeper using the new cap
   // keeper; the underlying bank store follows the fresh SDK context.
   bank:=RestrictedBank(raw,newCap)
   return newCtx,bank,newCap
 }
 return bankHarness{ctx:ctx,bank:raw,cap:cap,account:ak,restart:restart}
}
func (h bankHarness) genesisFund(t *testing.T,amount int64) {
 t.Helper()
 genesisMinter := authtypes.NewEmptyModuleAccount("genesisfixture",authtypes.Minter)
 h.account.EXPECT().GetModuleAccount(h.ctx,"genesisfixture").Return(genesisMinter)
 if err:=h.bank.MintCoins(h.ctx,"genesisfixture",
   sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,amount)));err!=nil {
   t.Fatalf("in-memory genesis arrangement failed: %v",err)
 }
}
func TestActualSDKBankKeeperProhibitsAllNativePrviMintingAfterGenesis(t *testing.T) {
 h:=newRealBankHarness(t)
 h.genesisFund(t,100)
 if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil {t.Fatal(err)}
 restricted:=RestrictedBank(h.bank,h.cap)
 before:=restricted.GetSupply(h.ctx,BaseDenom).Amount.String()
 for _,module:=range []string{"mint","erc20","transfer","evm","unauthorized"} {
   err:=restricted.MintCoins(h.ctx,module,sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1)))
   if !errors.Is(err,ErrMintForbidden){t.Fatalf("%s: expected PRVI mint denial; got %v",module,err)}
   if restricted.GetSupply(h.ctx,BaseDenom).Amount.String()!=before {
     t.Fatalf("%s: rejected mint mutated native supply",module)
   }
 }
 if _,err:=h.cap.Snapshot(h.ctx);err!=nil {t.Fatal(err)}
}
func TestActualSDKBankMixedDenomsFailBeforeAnyWrite(t *testing.T){
 h:=newRealBankHarness(t)
 h.genesisFund(t,100)
 if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil {t.Fatal(err)}
 k:=RestrictedBank(h.bank,h.cap)
 before:=k.GetSupply(h.ctx,BaseDenom).Amount.String()
 err:=k.MintCoins(h.ctx,"mint",sdk.NewCoins(
   sdk.NewInt64Coin(BaseDenom,1),sdk.NewInt64Coin("atest",55)))
 if !errors.Is(err,ErrMintForbidden){t.Fatal(err)}
 if k.GetSupply(h.ctx,BaseDenom).Amount.String()!=before || k.GetSupply(h.ctx,"atest").Amount.IsPositive() {
   t.Fatal("partial mint changed native or disposable supply")
 }
}
func TestActualSDKBankAllowsOtherDenomAfterCapInitialized(t *testing.T){
 h:=newRealBankHarness(t)
 h.genesisFund(t,100)
 if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil {t.Fatal(err)}
 k:=RestrictedBank(h.bank,h.cap)
 minter:=authtypes.NewEmptyModuleAccount("example",authtypes.Minter)
 h.account.EXPECT().GetModuleAccount(h.ctx,"example").Return(minter)
 if err:=k.MintCoins(h.ctx,"example",sdk.NewCoins(sdk.NewInt64Coin("atest",4)));err!=nil {t.Fatal(err)}
 if k.GetSupply(h.ctx,"atest").Amount.String()!="4" {t.Fatal("other denom failed to mint")}
 if k.GetSupply(h.ctx,BaseDenom).Amount.String()!="100" {t.Fatal("foreign mint changed native PRVI")}
}
func TestActualSDKBankRefusesNativeMintBeforeCapInit(t *testing.T){
 h:=newRealBankHarness(t)
 k:=RestrictedBank(h.bank,h.cap)
 if err:=k.MintCoins(h.ctx,"mint",sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1)));!errors.Is(err,ErrNotInitialized) {
   t.Fatal(err)
 }
 if k.GetSupply(h.ctx,BaseDenom).Amount.IsPositive() {t.Fatal("minted native units without initialized store")}
 // Legitimate unrelated bank minters can still initialize modules before
 // the separate native PRVI genesis supply has been reconciled.
 initialMinter:=authtypes.NewEmptyModuleAccount("genesisother",authtypes.Minter)
 h.account.EXPECT().GetModuleAccount(h.ctx,"genesisother").Return(initialMinter)
 if err:=k.MintCoins(h.ctx,"genesisother",sdk.NewCoins(sdk.NewInt64Coin("atest",2)));err!=nil {t.Fatal(err)}
 if k.GetSupply(h.ctx,"atest").Amount.String()!="2" {t.Fatal("unrelated genesis mint failed")}
 if k.GetSupply(h.ctx,BaseDenom).Amount.IsPositive() {t.Fatal("other denom mint changed PRVI supply")}
}

// Unrestricted bank copy could mint PRVI and bypass the restriction. This is
// an intentional demonstration that the future app must NEVER retain one;
// this test does not normalize or approve that vulnerability.
func TestUnrestrictedKeeperCopiesRemainARealBypassRisk(t *testing.T) {
 h:=newRealBankHarness(t)
 h.genesisFund(t,100)
 if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil {t.Fatal(err)}
 restricted:=RestrictedBank(h.bank,h.cap)
 minter:=authtypes.NewEmptyModuleAccount("badcopy",authtypes.Minter)
 h.account.EXPECT().GetModuleAccount(h.ctx,"badcopy").Return(minter)
 if err:=h.bank.MintCoins(h.ctx,"badcopy",sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1)));err!=nil {t.Fatal(err)}
 if restricted.GetSupply(h.ctx,BaseDenom).Amount.String()!="101" {
   t.Fatal("expected to reveal unguarded old bank keeper bypass")
 }
 if !errors.Is(h.cap.Reconcile(h.ctx,h.bank),ErrUnexpectedSupply) {
   t.Fatal("periodic reconciliation must flag bypassed supply growth")
 }
}

func TestActualSDKPersistentGenesisSurvivesCommitAndFreshMultistore(t *testing.T) {
 h:=newRealBankHarness(t)
 h.genesisFund(t,100)
 if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil {t.Fatal(err)}
 expected,err:=h.cap.Snapshot(h.ctx)
 if err!=nil {t.Fatal(err)}
 // Real persistent SDK multistore commit, followed by reconstructing and
 // loading a completely fresh multistore and a new cap keeper.
 restartedCtx,restricted,newCap:=h.restart(t)
 actual,err:=newCap.Snapshot(restartedCtx)
 if err!=nil || expected!=actual {t.Fatalf("persistent cap record disappeared after chain store reopen: %+v, %v",actual,err)}
 if got:=restricted.GetSupply(restartedCtx,BaseDenom).Amount.String();got!="100" {
   t.Fatalf("PRVI bank state lost after commit/reopen: %s",got)
 }
 if err:=restricted.MintCoins(restartedCtx,"mint",
   sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1)));!errors.Is(err,ErrMintForbidden) {
   t.Fatalf("restarted chain allowed unauthorized PRVI mint: %v",err)
 }
 if got:=restricted.GetSupply(restartedCtx,BaseDenom).Amount.String();got!="100" {
   t.Fatalf("rejected post-restart mint changed bank supply: %s",got)
 }
 if err:=newCap.InitGenesis(restartedCtx,"100",restricted);!errors.Is(err,ErrAlreadyInitialized) {
   t.Fatalf("restarting or upgrading attempted to reset lifetime issuance: %v",err)
 }
 if err:=newCap.Reconcile(restartedCtx,restricted);err!=nil {t.Fatalf("post-restart supply invariant broken: %v",err)}
}

func TestActualSDKUninitializedCapPersistsAsUninitializedAcrossCommit(t *testing.T) {
 h:=newRealBankHarness(t)
 ctx,bank,cap:=h.restart(t)
 if _,err:=cap.Snapshot(ctx);!errors.Is(err,ErrNotInitialized) {
   t.Fatalf("uninitialized chain must not silently create PRVI cap: %v",err)
 }
 if err:=bank.MintCoins(ctx,"mint",
   sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1)));!errors.Is(err,ErrNotInitialized) {
   t.Fatalf("missing genesis cap must deny new PRVI after restart: %v",err)
 }
}
