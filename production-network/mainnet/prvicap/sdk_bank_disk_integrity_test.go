package prvicap

// Security regressions against independently mounted, committed GoLevelDB-
// backed Cosmos SDK v0.54.3 bank and cap IAVL trees.
//
// These fixtures prove an untracked +1 aprvi direct balance mutation cannot
// disappear after a database commit/reopen, and damaged cap state cannot
// silently reset the genesis mint restriction. All balances are valueless,
// local, disposable; NO financial PRVI, validator keys or network.
import (
    "bytes"
    "errors"
    "path/filepath"
    "testing"
    "time"

    "cosmossdk.io/log/v2"
    dbm "github.com/cosmos/cosmos-db"
    cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
    "go.uber.org/mock/gomock"
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
)

type committedPriviDiskHarness struct {
    ctx sdk.Context
    bank bankkeeper.BaseKeeper
    cap Keeper
    corruptCapRecord func([]byte) error
    mintModuleAddr sdk.AccAddress
    commitAndReopen func(*testing.T) (sdk.Context,bankkeeper.BaseKeeper,Keeper)
}

// Actual test database files are confined to t.TempDir, never on the
// operator's VPS. Three independent LevelDBs avoid IAVL node collisions.
func newCommittedPriviDiskHarness(t *testing.T) committedPriviDiskHarness {
    t.Helper()
    directory:=t.TempDir()
    open:=func(name string) dbm.DB {
        result,err:=dbm.NewGoLevelDB(name,filepath.Join(directory,"sdk"),nil)
        if err!=nil {t.Fatal(err)}
        t.Cleanup(func(){ _=result.Close() })
        return result
    }
    rootDB,bankDB,capDB:=open("root"),open("bank"),open("cap")
    objectDB:=dbm.NewMemDB()
    logger:=log.NewNopLogger()
    bankKey:=storetypes.NewKVStoreKey(banktypes.StoreKey)
    capKey:=storetypes.NewKVStoreKey("prvicap")
    objKey:=storetypes.NewObjectStoreKey(banktypes.ObjectStoreKey)
    ms:=store.NewCommitMultiStore(rootDB,logger)
    ms.MountStoreWithDB(bankKey,storetypes.StoreTypeIAVL,bankDB)
    ms.MountStoreWithDB(capKey,storetypes.StoreTypeIAVL,capDB)
    ms.MountStoreWithDB(objKey,storetypes.StoreTypeObject,objectDB)
    if err:=ms.LoadLatestVersion();err!=nil {t.Fatal(err)}
    ctx:=sdk.NewContext(ms,cmtproto.Header{Height:1,Time:time.Unix(1800000000,0)},false,logger)
    ctrl:=gomock.NewController(t)
    accounts:=banktestutil.NewMockAccountKeeper(ctrl)
    accounts.EXPECT().AddressCodec().Return(address.NewBech32Codec("cosmos")).AnyTimes()
    codec:=moduletestutil.MakeTestEncodingConfig()
    bank:=bankkeeper.NewBaseKeeper(codec.Codec,
        runtime.NewKVStoreService(bankKey),accounts,
        map[string]bool{},authtypes.NewModuleAddress(govtypes.ModuleName).String(),logger)
    bank=bank.WithObjStoreKey(objKey)
    cap,err:=New(runtime.NewKVStoreService(capKey))
    if err!=nil {t.Fatal(err)}
    mintAccount:=authtypes.NewEmptyModuleAccount("genesisfixture",authtypes.Minter)
    accounts.EXPECT().GetModuleAccount(ctx,"genesisfixture").Return(mintAccount)
    if err:=bank.MintCoins(ctx,"genesisfixture",sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,100)));err!=nil {
        t.Fatalf("disposable SDK bank supply initialization failed: %v",err)
    }
    if err:=cap.InitGenesis(ctx,"100",bank);err!=nil {t.Fatalf("commit fixture cap genesis: %v",err)}
    if err:=cap.Reconcile(ctx,bank);err!=nil {t.Fatalf("baseline balance conservation: %v",err)}
    reopen:=func(t *testing.T) (sdk.Context,bankkeeper.BaseKeeper,Keeper) {
        t.Helper()
        // Persistent write then independent SDK multistore open: this is
        // strictly stronger than a new keeper over the same in-memory view.
        ms.Commit()
        reopened:=store.NewCommitMultiStore(rootDB,logger)
        reopened.MountStoreWithDB(bankKey,storetypes.StoreTypeIAVL,bankDB)
        reopened.MountStoreWithDB(capKey,storetypes.StoreTypeIAVL,capDB)
        reopened.MountStoreWithDB(objKey,storetypes.StoreTypeObject,objectDB)
        if err:=reopened.LoadLatestVersion();err!=nil {t.Fatal(err)}
        newCtx:=sdk.NewContext(reopened,cmtproto.Header{Height:2,Time:time.Unix(1800000001,0)},false,logger)
        newCap,err:=New(runtime.NewKVStoreService(capKey))
        if err!=nil {t.Fatal(err)}
        return newCtx,RestrictedBank(bank,newCap),newCap
    }
    // Direct consensus-store mutation is intentionally available only in
    // this disposable corruption fixture. Never expose in a live app API.
    writeBadCap:=func(value []byte) error {
        kv:=runtime.NewKVStoreService(capKey).OpenKVStore(ctx)
        return kv.Set(keyGenesis,value)
    }
    return committedPriviDiskHarness{
        ctx:ctx,bank:bank,cap:cap,commitAndReopen:reopen,
        corruptCapRecord:writeBadCap,
        mintModuleAddr:mintAccount.GetAddress(),
    }
}

func TestCommittedDiskStateRejectsUntrackedNativeBalanceAfterReopen(t *testing.T) {
    h:=newCommittedPriviDiskHarness(t)
    // This dangerous SDK API edits account balances WITHOUT updating
    // the bank's declared native supply counter. Real applications must
    // audit and eliminate this class of unchecked account writes.
    addr:=sdk.AccAddress(bytes.Repeat([]byte{0x51},20))
    if err:=h.bank.UncheckedSetBalance(h.ctx,addr,sdk.NewInt64Coin(BaseDenom,1));err!=nil {
        t.Fatalf("disposable unchecked +1 native balance: %v",err)
    }
    if got:=h.bank.GetSupply(h.ctx,BaseDenom).Amount.String();got!="100" {
        t.Fatalf("setup must not alter declared supply counter: %s",got)
    }
    ctx,bank,cap:=h.commitAndReopen(t)
    if got:=bank.GetSupply(ctx,BaseDenom).Amount.String();got!="100" {
        t.Fatalf("unexpected post-reopen declared supply: %s",got)
    }
    if err:=cap.Reconcile(ctx,bank);!errors.Is(err,ErrUnexpectedSupply) {
        t.Fatalf("reopened persisted native +1 balance was NOT detected: %v",err)
    }
    if err:=bank.MintCoins(ctx,"mint",sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1)));!errors.Is(err,ErrMintForbidden) {
        t.Fatalf("native mint was allowed on tampered persisted state: %v",err)
    }
}

func TestCommittedDiskStateProhibitsCapResetAfterReopen(t *testing.T) {
    h:=newCommittedPriviDiskHarness(t)
    // Reopen the actual committed cap and verify a second InitGenesis
    // cannot reset its original lifetime issuance state.
    ctx,bank,cap:=h.commitAndReopen(t)
    if err:=cap.InitGenesis(ctx,"1",bank);!errors.Is(err,ErrAlreadyInitialized) {
        t.Fatalf("persistent cap record was reset after reopen: %v",err)
    }
    if snapshot,err:=cap.Snapshot(ctx);err!=nil || snapshot.GenesisBase!="100" {
        t.Fatalf("persistent cap record mismatch: %+v / %v",snapshot,err)
    }
}


func TestCommittedDiskCapCorruptionDeniesMintAndRestart(t *testing.T) {
    h:=newCommittedPriviDiskHarness(t)
    // Tamper the actual KV record on a disposable GoLevelDB/IAVL tree,
    // not a mocked service or in-process cap counter.
    if err:=h.corruptCapRecord([]byte("0"));err!=nil {
        t.Fatalf("inject invalid persisted cap: %v",err)
    }
    ctx,bank,cap:=h.commitAndReopen(t)
    if _,err:=cap.Snapshot(ctx);!errors.Is(err,ErrStoreCorrupt) {
        t.Fatalf("corrupt cap was accepted after DB reopen: %v",err)
    }
    if err:=bank.MintCoins(ctx,"mint",
        sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,1)));!errors.Is(err,ErrStoreCorrupt) {
        t.Fatalf("corrupt cap allowed financial denomination mint: %v",err)
    }
    if err:=cap.Reconcile(ctx,bank);!errors.Is(err,ErrStoreCorrupt) {
        t.Fatalf("corrupt cap allowed block-boundary reconcile: %v",err)
    }
    if err:=cap.InitGenesis(ctx,"100",bank);!errors.Is(err,ErrAlreadyInitialized) {
        t.Fatalf("corrupt cap was silently reinitialized: %v",err)
    }
}

// This is a deliberately *passing proof of a known gap*, NOT a test that
// claims Privi detects supply-neutral unauthorized balance redistribution.
// Aggregating balances to the native supply amount cannot authenticate
// individual writes: a malicious caller of UncheckedSetBalance can shift
// one unit between two accounts with no change to total supply.
func TestCommittedDiskSupplyNeutralTamperingIsNotDetectedByAggregateGuard(t *testing.T) {
    h:=newCommittedPriviDiskHarness(t)
    src:=h.bank.GetBalance(h.ctx,h.mintModuleAddr,BaseDenom)
    if src.Amount.String()!="100" {t.Fatalf("unexpected fixture module balance: %s",src)}
    destination:=sdk.AccAddress(bytes.Repeat([]byte{0x66},20))
    if err:=h.bank.UncheckedSetBalance(h.ctx,h.mintModuleAddr,
        sdk.NewInt64Coin(BaseDenom,99));err!=nil {t.Fatal(err)}
    if err:=h.bank.UncheckedSetBalance(h.ctx,destination,
        sdk.NewInt64Coin(BaseDenom,1));err!=nil {t.Fatal(err)}
    if got:=h.bank.GetSupply(h.ctx,BaseDenom).Amount.String();got!="100" {
        t.Fatalf("expected supply-neutral modification: %s",got)
    }
    // This succeeds by design: aggregate conservation is insufficient to
    // validate authorization or transfer transaction provenance.
    if err:=h.cap.Reconcile(h.ctx,h.bank);err!=nil {
        t.Fatalf("known supply-neutral gap unexpectedly disappeared: %v",err)
    }
    ctx,bank,cap:=h.commitAndReopen(t)
    if got:=bank.GetBalance(ctx,destination,BaseDenom).Amount.String();got!="1" {
        t.Fatalf("tampered account did not persist: %s",got)
    }
    if err:=cap.Reconcile(ctx,bank);err!=nil {
        t.Fatalf("known persisted supply-neutral gap unexpectedly disappeared: %v",err)
    }
}
