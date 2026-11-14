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
 // Retain only the in-memory test database and mounted store keys so a
 // separate CommitMultiStore can reopen previously committed state.
 db dbm.DB
 // Each IAVL store needs its own backing database. Sharing the root
 // multistore DB between bank and cap IAVL trees causes both to attempt
 // to save conflicting nodes for the same version.
 bankDB dbm.DB
 capDB dbm.DB
 objDB dbm.DB
 bankKey *storetypes.KVStoreKey
 capKey *storetypes.KVStoreKey
 objKey *storetypes.ObjectStoreKey
}

func newRealBankHarness(t *testing.T) bankHarness {
 t.Helper()
 db := dbm.NewMemDB()
 bankDB := dbm.NewMemDB()
 capDB := dbm.NewMemDB()
 objDB := dbm.NewMemDB()
 cms := store.NewCommitMultiStore(db,log.NewNopLogger())
 bankKey := storetypes.NewKVStoreKey(banktypes.StoreKey)
 capKey := storetypes.NewKVStoreKey("prvicap")
 objKey := storetypes.NewObjectStoreKey(banktypes.ObjectStoreKey)
 cms.MountStoreWithDB(bankKey,storetypes.StoreTypeIAVL,bankDB)
 cms.MountStoreWithDB(capKey,storetypes.StoreTypeIAVL,capDB)
 cms.MountStoreWithDB(objKey,storetypes.StoreTypeObject,objDB)
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
 return bankHarness{ctx:ctx,bank:raw,cap:cap,account:ak,
  db:db,bankDB:bankDB,capDB:capDB,objDB:objDB,
  bankKey:bankKey,capKey:capKey,objKey:objKey}
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

// This is an intentional FAIL-OPEN threat demonstration, not a security fix.
// A raw keeper can mint and burn aprvi before a periodic reconciliation,
// returning supply to its prior value. End-of-block checks cannot prove that
// an unauthorized intermediate issuance never occurred. The production app
// must prevent the mint at the mutation boundary before relying on Reconcile.
func TestRawKeeperSameBlockMintBurnEvadesSupplyReconciliation(t *testing.T) {
 h:=newRealBankHarness(t)
 h.genesisFund(t,100)
 if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil {t.Fatal(err)}
 before:=h.bank.GetSupply(h.ctx,BaseDenom).Amount.String()
 if before!="100" {t.Fatalf("unexpected fixture genesis supply %s",before)}
 minter:=authtypes.NewEmptyModuleAccount("badcopy",authtypes.Minter,authtypes.Burner)
 h.account.EXPECT().GetModuleAccount(h.ctx,"badcopy").Return(minter).AnyTimes()
 // SDK bank balance reads consult the account keeper during burn; supply a real module account fixture.
 h.account.EXPECT().GetAccount(gomock.Any(),gomock.Any()).Return(minter).AnyTimes()
 coin:=sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1))
 if err:=h.bank.MintCoins(h.ctx,"badcopy",coin);err!=nil {t.Fatalf("raw keeper bypass mint: %v",err)}
 if got:=h.bank.GetSupply(h.ctx,BaseDenom).Amount.String();got!="101" {
   t.Fatalf("expected intermediate unauthorized supply of 101, got %s",got)
 }
 if err:=h.bank.BurnCoins(h.ctx,"badcopy",coin);err!=nil {t.Fatalf("raw keeper burn: %v",err)}
 if got:=h.bank.GetSupply(h.ctx,BaseDenom).Amount.String();got!=before {
   t.Fatalf("supply after mint/burn = %s, want %s",got,before)
 }
 if err:=h.cap.Reconcile(h.ctx,h.bank);err!=nil {
   t.Fatalf("supply-only reconciliation unexpectedly detected transient issuance: %v",err)
 }
 state,err:=h.cap.Snapshot(h.ctx)
 if err!=nil {t.Fatal(err)}
 if state.GenesisBase!="100" || state.LifetimeIssuedBase!="100" {
   t.Fatalf("cap record unexpectedly changed: %+v",state)
 }
 // A clean immutable record and final supply do NOT establish that no
 // unauthorized aprvi was issued transiently. This remains a NO-GO finding.
}


// Burning outstanding native PRVI never restores issuance permission.
// This checks the guarded SDK API, NOT unrestricted keeper aliases.
func TestRestrictedBankRejectsRemintAfterNativeBurn(t *testing.T) {
 h:=newRealBankHarness(t)
 h.genesisFund(t,100)
 if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil {t.Fatal(err)}
 guarded:=RestrictedBank(h.bank,h.cap)
 burner:=authtypes.NewEmptyModuleAccount("genesisfixture",authtypes.Minter,authtypes.Burner)
 h.account.EXPECT().GetModuleAccount(h.ctx,"genesisfixture").Return(burner).AnyTimes()
 h.account.EXPECT().GetAccount(gomock.Any(),gomock.Any()).Return(burner).AnyTimes()
 native:=sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1))
 if err:=guarded.BurnCoins(h.ctx,"genesisfixture",native);err!=nil {t.Fatal(err)}
 if got:=guarded.GetSupply(h.ctx,BaseDenom).Amount.String();got!="99" {
   t.Fatalf("fixture burn supply = %s, expected 99",got)
 }
 if err:=h.cap.Reconcile(h.ctx,guarded);err!=nil {t.Fatalf("burn should preserve cap invariant: %v",err)}
 if err:=guarded.MintCoins(h.ctx,"genesisfixture",native);!errors.Is(err,ErrMintForbidden) {
   t.Fatalf("native reissuance after burn must fail, got %v",err)
 }
 if got:=guarded.GetSupply(h.ctx,BaseDenom).Amount.String();got!="99" {
   t.Fatalf("rejected remint changed supply to %s",got)
 }
 // A mixed-denomination request must fail atomically even after burning
 // native supply; a rejected aprvi reissuance must not mint unrelated units.
 mixed:=sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1),sdk.NewInt64Coin("atest",7))
 if err:=guarded.MintCoins(h.ctx,"genesisfixture",mixed);!errors.Is(err,ErrMintForbidden) {
   t.Fatalf("mixed-denomination remint must fail before writes, got %v",err)
 }
 if got:=guarded.GetSupply(h.ctx,BaseDenom).Amount.String();got!="99" {
   t.Fatalf("mixed mint changed native supply to %s",got)
 }
 if got:=guarded.GetSupply(h.ctx,"atest").Amount.String();got!="0" {
   t.Fatalf("rejected mixed mint leaked foreign-denom supply %s",got)
 }
 state,err:=h.cap.Snapshot(h.ctx)
 if err!=nil {t.Fatal(err)}
 if state.GenesisBase!="100" || state.LifetimeIssuedBase!="100" {
   t.Fatalf("burn/remint changed immutable issuance record: %+v",state)
 }
}


// Reject native/foreign-denom mixed issuance before the cap is initialized.
// This proves only the restricted keeper path, not raw keeper safety.
func TestRestrictedBankRejectsMixedMintBeforeCapInitializationAtomically(t *testing.T) {
 h:=newRealBankHarness(t)
 guarded:=RestrictedBank(h.bank,h.cap)
 coins:=sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1),sdk.NewInt64Coin("atest",7))
 if err:=guarded.MintCoins(h.ctx,"mint",coins);!errors.Is(err,ErrNotInitialized) {
  t.Fatalf("expected uninitialized cap rejection, got %v",err)
 }
 if got:=guarded.GetSupply(h.ctx,BaseDenom).Amount.String();got!="0" {
  t.Fatalf("rejected mint modified native supply: %s",got)
 }
 if got:=guarded.GetSupply(h.ctx,"atest").Amount.String();got!="0" {
  t.Fatalf("rejected mint created other denomination: %s",got)
 }
 if _,err:=h.cap.Snapshot(h.ctx);!errors.Is(err,ErrNotInitialized) {
  t.Fatalf("rejected mint initialized cap state: %v",err)
 }
}
