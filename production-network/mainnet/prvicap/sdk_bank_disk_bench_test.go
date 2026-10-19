package prvicap

// Disk-backed SDK/IAVL v0.54.3 benchmark on a *disposable* GoLevelDB tree.
//
// This extends the previously validated MemDB SDK account-walk benchmark by
// committing real bank+cap stores, reopening a fresh multistore, then timing
// immutable native PRVI supply reconciliation against committed state.
//
// It is still NOT an end-to-end block benchmark: GitHub runner storage, small
// state sizes, one process, warm cache, and no CometBFT/EVM/IO contention.
// No production keys, genesis, signing activity or financial PRVI.
import (
    "encoding/binary"
    "fmt"
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

func BenchmarkDiskBackedSDKNativeConservationScan(b *testing.B) {
    for _, accounts := range []int{100, 1000, 5000} {
        b.Run(fmt.Sprintf("committed-accounts-%d", accounts), func(b *testing.B) {
            b.StopTimer()
            rootDir:=b.TempDir()
            open:=func(name string) dbm.DB {
                db,err:=dbm.NewGoLevelDB(name,filepath.Join(rootDir,"iavl"),nil)
                if err!=nil {b.Fatalf("disposable LevelDB open: %v",err)}
                b.Cleanup(func(){ _=db.Close() })
                return db
            }
            // Separate IAVL trees must never share an unprefixed DB.
            rootDB,bankDB,capDB:=open("root"),open("bank"),open("cap")
            objDB:=dbm.NewMemDB()
            logger:=log.NewNopLogger()
            bankKey:=storetypes.NewKVStoreKey(banktypes.StoreKey)
            capKey:=storetypes.NewKVStoreKey(StoreKey)
            objKey:=storetypes.NewObjectStoreKey(banktypes.ObjectStoreKey)
            cms:=store.NewCommitMultiStore(rootDB,logger)
            cms.MountStoreWithDB(bankKey,storetypes.StoreTypeIAVL,bankDB)
            cms.MountStoreWithDB(capKey,storetypes.StoreTypeIAVL,capDB)
            cms.MountStoreWithDB(objKey,storetypes.StoreTypeObject,objDB)
            if err:=cms.LoadLatestVersion();err!=nil {b.Fatal(err)}
            ctx:=sdk.NewContext(cms,cmtproto.Header{Height:1,Time:time.Unix(1800000000,0)},false,logger)

            ctrl:=gomock.NewController(b)
            ak:=banktestutil.NewMockAccountKeeper(ctrl)
            ak.EXPECT().AddressCodec().Return(address.NewBech32Codec("cosmos")).AnyTimes()
            codec:=moduletestutil.MakeTestEncodingConfig()
            raw:=bankkeeper.NewBaseKeeper(codec.Codec,runtime.NewKVStoreService(bankKey),
                ak,map[string]bool{},authtypes.NewModuleAddress(govtypes.ModuleName).String(),logger)
            raw=raw.WithObjStoreKey(objKey)
            keeper,err:=New(runtime.NewKVStoreService(capKey))
            if err!=nil {b.Fatal(err)}
            genesisMinter:=authtypes.NewEmptyModuleAccount("genesisfixture",authtypes.Minter)
            ak.EXPECT().GetModuleAccount(ctx,"genesisfixture").Return(genesisMinter)
            if err:=raw.MintCoins(ctx,"genesisfixture",
                sdk.NewCoins(sdk.NewInt64Coin(BaseDenom,100)));err!=nil {b.Fatal(err)}
            for i:=0;i<accounts;i++ {
                addr:=make([]byte,20)
                binary.BigEndian.PutUint64(addr[12:],uint64(i+1))
                if err:=raw.UncheckedSetBalance(ctx,sdk.AccAddress(addr),
                    sdk.NewInt64Coin("atest",1));err!=nil {b.Fatal(err)}
            }
            if err:=keeper.InitGenesis(ctx,"100",raw);err!=nil {b.Fatal(err)}
            if err:=keeper.Reconcile(ctx,raw);err!=nil {b.Fatal(err)}
            // Commit both independent IAVL trees; then open a *different*
            // SDK multistore rooted at the committed disk-backed versions.
            cms.Commit()
            reopened:=store.NewCommitMultiStore(rootDB,logger)
            reopened.MountStoreWithDB(bankKey,storetypes.StoreTypeIAVL,bankDB)
            reopened.MountStoreWithDB(capKey,storetypes.StoreTypeIAVL,capDB)
            reopened.MountStoreWithDB(objKey,storetypes.StoreTypeObject,objDB)
            if err:=reopened.LoadLatestVersion();err!=nil {b.Fatal(err)}
            readCtx:=sdk.NewContext(reopened,cmtproto.Header{
                Height:2,Time:time.Unix(1800000001,0),
            },false,logger)
            // It is essential this cap keeper reads actual persisted genesis,
            // not the old context or a process-local counter.
            reopenedCap,err:=New(runtime.NewKVStoreService(capKey))
            if err!=nil {b.Fatal(err)}
            restricted:=RestrictedBank(raw,reopenedCap)
            if err:=reopenedCap.Reconcile(readCtx,restricted);err!=nil {
                b.Fatalf("disk-backed baseline reconciliation: %v",err)
            }
            b.ReportAllocs()
            b.ResetTimer()
            b.StartTimer()
            for i:=0;i<b.N;i++ {
                if err:=reopenedCap.Reconcile(readCtx,restricted);err!=nil {b.Fatal(err)}
            }
        })
    }
}
