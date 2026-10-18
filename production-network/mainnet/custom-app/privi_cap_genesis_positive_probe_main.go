// A valueless *positive* customized Cosmos EVM InitChain test.
// This uses an ephemeral on-disk CI database and a disposable consensus test pubkey.
// A fresh child process opens the same DB to avoid upstream Cosmos EVM's
// process-global fork activation duplication on same-process app reconstruction.
// Never a production signer, deployable genesis or financial PRVI.
package main

import (
    "bytes"
    "encoding/json"
    "errors"
    "fmt"
    "os"
    "os/exec"
    "time"

    "cosmossdk.io/log/v2"
    sdkmath "cosmossdk.io/math"
    abci "github.com/cometbft/cometbft/abci/types"
    cmttypes "github.com/cometbft/cometbft/types"
    cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
    dbm "github.com/cosmos/cosmos-db"
    "github.com/cosmos/evm/evmd"
    "github.com/cosmos/evm/evmd/prvicap"
    vmtypes "github.com/cosmos/evm/x/vm/types"
    "github.com/cosmos/cosmos-sdk/baseapp"
    simtestutil "github.com/cosmos/cosmos-sdk/testutil/sims"
    sdk "github.com/cosmos/cosmos-sdk/types"
    authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
    banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
    stakingtypes "github.com/cosmos/cosmos-sdk/x/staking/types"
    minttypes "github.com/cosmos/cosmos-sdk/x/mint/types"
    slashingtypes "github.com/cosmos/cosmos-sdk/x/slashing/types"
    "github.com/cosmos/cosmos-sdk/testutil/mock"
)

func probe() error {
    const chainID = "privi-ci-only-not-financial-1"
    // A disk-backed TEMPORARY database is necessary to prove restart in
    // a second OS process. CI removes it after the child exits.
    dir,err:=os.MkdirTemp("","privi-valueless-restart-*")
    if err!=nil {return err}
    defer os.RemoveAll(dir)
    db,err:=dbm.NewGoLevelDB("privi-ephemeral",dir,nil)
    if err!=nil {return fmt.Errorf("open disposable database: %w",err)}
    defer db.Close()
    app := evmd.NewExampleApp(log.NewNopLogger(), db, true,
        simtestutil.EmptyAppOptions{}, baseapp.SetChainID(chainID))
    genesis := app.DefaultGenesis()

    // The built-in Cosmos SDK fixture provides the correct bonded-validator,
    // auth and bank genesis shape. Signing material is disposable in-memory CI.
    pv := mock.NewPV()
    pubKey, err := pv.GetPubKey()
    if err != nil {return fmt.Errorf("ephemeral mock pubkey: %w",err)}
    validators := cmttypes.NewValidatorSet([]*cmttypes.Validator{cmttypes.NewValidator(pubKey, 1)})
    address := sdk.AccAddress(bytes.Repeat([]byte{0x42},20))
    account := authtypes.NewBaseAccount(address,nil,0,0)
    allocation := sdk.NewCoins(
        sdk.NewCoin(prvicap.BaseDenom,sdkmath.NewInt(2_000_000_000_000_000_000)),
    )
    bal := banktypes.Balance{Address: account.GetAddress().String(), Coins: allocation}
    genesis, err = simtestutil.GenesisStateWithValSet(
        app.AppCodec(), genesis, validators,
        []authtypes.GenesisAccount{account}, bal,
    )
    if err!=nil {return fmt.Errorf("build valueless SDK fixture: %w",err)}
    // Cosmos EVM v0.7.3 requires EVM denomination metadata in bank genesis.
    // The default upstream "stake" cannot stand in for native Privi PRVI.
    // This CI-only fixture sets the EVM currency to aprvi with 18 decimals.
    var bankGenesis banktypes.GenesisState
    if err:=app.AppCodec().UnmarshalJSON(genesis[banktypes.ModuleName], &bankGenesis);err!=nil {return err}
    // The fixture library injects one SDK default bonded-pool "stake" coin.
    // Replace that DISPOSABLE fixture with native aprvi and rederive its
    // declared bank supply before initialization of our cap keeper.
    bondedPool := authtypes.NewModuleAddress(stakingtypes.BondedPoolName).String()
    poolFound:=false
    for i:=range bankGenesis.Balances {
        if bankGenesis.Balances[i].Address==bondedPool {
            bankGenesis.Balances[i].Coins = sdk.NewCoins(
                sdk.NewCoin(prvicap.BaseDenom,sdkmath.NewInt(1_000_000_000_000_000_000)))
            poolFound=true
        }
    }
    if !poolFound {return fmt.Errorf("fixture bonded pool balance missing")}
    bankGenesis.Supply=sdk.NewCoins(sdk.NewCoin(
        prvicap.BaseDenom,sdkmath.NewInt(3_000_000_000_000_000_000)))
    bankGenesis.DenomMetadata=append(bankGenesis.DenomMetadata,banktypes.Metadata{
        Description: "Privi PRVI (ephemeral developer fixture, not financial token)",
        DenomUnits: []*banktypes.DenomUnit{
            {Denom:prvicap.BaseDenom, Exponent:0},
            {Denom:"PRVI", Exponent:18},
        },
        Base:prvicap.BaseDenom, Display:"PRVI", Name:"Privi", Symbol:"PRVI",
    })
    genesis[banktypes.ModuleName]=app.AppCodec().MustMarshalJSON(&bankGenesis)
    var evmGenesis vmtypes.GenesisState
    if err:=app.AppCodec().UnmarshalJSON(genesis[vmtypes.ModuleName], &evmGenesis);err!=nil {return err}
    evmGenesis.Params.EvmDenom=prvicap.BaseDenom
    genesis[vmtypes.ModuleName]=app.AppCodec().MustMarshalJSON(&evmGenesis)
    // Proof of a native chain: PRVI powers EVM, validator bonds and mint
    // module. Post-genesis APRVI issuance is permanently forbidden; the
    // module fixture must not schedule nonzero inflation.
    var stakingGenesis stakingtypes.GenesisState
    if err:=app.AppCodec().UnmarshalJSON(genesis[stakingtypes.ModuleName], &stakingGenesis);err!=nil {return err}
    stakingGenesis.Params.BondDenom=prvicap.BaseDenom
    genesis[stakingtypes.ModuleName]=app.AppCodec().MustMarshalJSON(&stakingGenesis)
    // Running a real FinalizeBlock requires the slashing module to know the
    // ephemeral validator's signing record, unlike InitChain-only fixtures.
    // Reuse the exact pinned Cosmos EVM integration network's genesis shape.
    consAddress, err := app.StakingKeeper.ConsensusAddressCodec().BytesToString(pubKey.Address())
    if err!=nil {return fmt.Errorf("fixture consensus address: %w",err)}
    var slashingGenesis slashingtypes.GenesisState
    if err:=app.AppCodec().UnmarshalJSON(genesis[slashingtypes.ModuleName],&slashingGenesis);err!=nil {return err}
    slashingGenesis.SigningInfos=[]slashingtypes.SigningInfo{{
        Address:consAddress,
        ValidatorSigningInfo:slashingtypes.ValidatorSigningInfo{
            Address:consAddress,
            JailedUntil:time.Unix(0,0).UTC(),
        },
    }}
    slashingGenesis.MissedBlocks=[]slashingtypes.ValidatorMissedBlocks{{Address:consAddress}}
    genesis[slashingtypes.ModuleName]=app.AppCodec().MustMarshalJSON(&slashingGenesis)

    var mintGenesis minttypes.GenesisState
    if err:=app.AppCodec().UnmarshalJSON(genesis[minttypes.ModuleName], &mintGenesis);err!=nil {return err}
    mintGenesis.Params.MintDenom=prvicap.BaseDenom
    mintGenesis.Params.InflationRateChange=sdkmath.LegacyZeroDec()
    mintGenesis.Params.InflationMax=sdkmath.LegacyZeroDec()
    mintGenesis.Params.InflationMin=sdkmath.LegacyZeroDec()
    mintGenesis.Minter.Inflation=sdkmath.LegacyZeroDec()
    mintGenesis.Minter.AnnualProvisions=sdkmath.LegacyZeroDec()
    genesis[minttypes.ModuleName]=app.AppCodec().MustMarshalJSON(&mintGenesis)
    raw, err := json.Marshal(genesis)
    if err!=nil {return fmt.Errorf("encode custom genesis fixture: %w",err)}
    resp, err := app.InitChain(&abci.RequestInitChain{
        ChainId:chainID,
        ConsensusParams:simtestutil.DefaultConsensusParams,
        AppStateBytes:raw,
    })
    if err!=nil {return fmt.Errorf("customized app InitChain rejected valid fixture: %w",err)}
    if resp==nil {return fmt.Errorf("nil InitChain response")}
    // Verify the REAL mounted, consensus-backed Privi cap keeper reads the
    // exact in-memory initial aprvi supply, and the FULL bank keeper injected
    // into the custom app refuses any post-genesis native mint operation.
    const expectedAPRVI = "3000000000000000000" // 3 valueless PRVI; NOT mainnet
    ctx := app.NewContextLegacy(false,cmtproto.Header{ChainID:chainID,Height:0})
    capBefore,err := app.PriviCapKeeper.Snapshot(ctx)
    if err!=nil {return fmt.Errorf("custom native genesis cap store not initialized: %w",err)}
    if capBefore.GenesisBase!=expectedAPRVI ||
        capBefore.LifetimeIssuedBase!=expectedAPRVI ||
        capBefore.MintPolicy!="NO_NEW_NATIVE_PRVI_MINTS" {
        return fmt.Errorf("incorrect native lifetime issuance: %+v",capBefore)
    }
    if got:=app.BankKeeper.GetSupply(ctx,prvicap.BaseDenom).Amount.String();got!=expectedAPRVI {
        return fmt.Errorf("native PRVI supply mismatch: %s",got)
    }
    err=app.BankKeeper.MintCoins(ctx,minttypes.ModuleName,
        sdk.NewCoins(sdk.NewInt64Coin(prvicap.BaseDenom,1)))
    if !errors.Is(err,prvicap.ErrMintForbidden) {
        return fmt.Errorf("SECURITY: customized bank keeper allowed native mint: %v",err)
    }
    fmt.Println("PASS: mounted native lifetime cap equals bank supply; actual injected bank keeper refuses mint")
    // Simulate a dangerous direct x/bank UncheckedSetBalance write: this
    // bypasses MintCoins and changes a real aprvi account WITHOUT changing
    // bank.Supply metadata. The cap's full balance-conservation check must
    // catch it. Restore the fixture before processing any block.
    original:=app.BankKeeper.GetBalance(ctx,address,prvicap.BaseDenom)
    if err:=app.BankKeeper.UncheckedSetBalance(ctx,address,
        sdk.NewCoin(prvicap.BaseDenom,original.Amount.Add(sdkmath.NewInt(1))));err!=nil {
        return fmt.Errorf("inject disposable untracked balance edit: %w",err)
    }
    if err:=app.PriviCapKeeper.Reconcile(ctx,app.BankKeeper); !errors.Is(err,prvicap.ErrUnexpectedSupply) {
        return fmt.Errorf("SECURITY: bank supply-vs-balances spoof not detected: %v",err)
    }
    if err:=app.BankKeeper.UncheckedSetBalance(ctx,address,original);err!=nil {
        return fmt.Errorf("restore disposable native account: %w",err)
    }
    if err:=app.PriviCapKeeper.Reconcile(ctx,app.BankKeeper);err!=nil {
        return fmt.Errorf("native balance not restored after adversarial probe: %w",err)
    }
    fmt.Println("PASS: native balance-conservation guard rejects actual unchecked +1 balance tampering")


    // Execute real Cosmos SDK Begin/EndBlock via ABCI FinalizeBlock on the
    // modified app; a compilation-only test cannot prove this. The ephemeral
    // one-validator commit data is ONLY for a disposable in-memory test.
    blockTime:=time.Unix(1800000000,0).UTC()
    votes:=make([]abci.VoteInfo,0,len(validators.Validators))
    for _,v:=range validators.Validators {
        votes=append(votes,abci.VoteInfo{
            Validator:abci.Validator{Address:v.Address,Power:v.VotingPower},
            BlockIdFlag:cmtproto.BlockIDFlagCommit,
        })
    }
    fin,err:=app.FinalizeBlock(&abci.RequestFinalizeBlock{
        Height:1, Time:blockTime, DecidedLastCommit:abci.CommitInfo{Votes:votes},
        NextValidatorsHash:validators.Hash(),
        ProposerAddress:validators.Proposer.Address,
        Hash:[]byte("privi-valueless-ci-height-1"),
    })
    if err!=nil {return fmt.Errorf("custom app FinalizeBlock height 1: %w",err)}
    if fin==nil {return fmt.Errorf("custom app returned nil FinalizeBlock")}
    if _,err=app.Commit();err!=nil {return fmt.Errorf("custom app Commit height 1: %w",err)}
    ctxAfter:=app.NewContextLegacy(true,cmtproto.Header{ChainID:chainID,Height:1})
    capAfter,err:=app.PriviCapKeeper.Snapshot(ctxAfter)
    if err!=nil {return fmt.Errorf("post-commit native cap store inaccessible: %w",err)}
    if capAfter!=capBefore {return fmt.Errorf("native cap state mutated after block: before=%+v after=%+v",capBefore,capAfter)}
    if supply:=app.BankKeeper.GetSupply(ctxAfter,prvicap.BaseDenom).Amount.String();supply!=expectedAPRVI {
        return fmt.Errorf("native aprvi supply changed after 1 finalized block: %s",supply)
    }
    fmt.Println("PASS: customized app FinalizeBlock/Commit height 1; native PRVI lifetime issuance and supply unchanged")
    // Another actual ABCI finalization exercises Begin/EndBlock supply
    // checks after the first successful commit (one epoch is insufficient
    // to demonstrate keeper state persistence).
    fin2,err:=app.FinalizeBlock(&abci.RequestFinalizeBlock{
        Height:2, Time:blockTime.Add(time.Second),
        DecidedLastCommit:abci.CommitInfo{Votes:votes},
        NextValidatorsHash:validators.Hash(),
        ProposerAddress:validators.Proposer.Address,
        Hash:app.LastCommitID().Hash,
    })
    if err!=nil {return fmt.Errorf("custom app FinalizeBlock height 2: %w",err)}
    if fin2==nil {return fmt.Errorf("custom app nil FinalizeBlock at height 2")}
    if _,err=app.Commit();err!=nil {return fmt.Errorf("custom app Commit height 2: %w",err)}
    if app.LastBlockHeight()!=2 {
        return fmt.Errorf("expected two persisted in-memory blocks; got %d",app.LastBlockHeight())
    }

    // Cosmos EVM sets Go process-global fork activation once. A second app
    // instantiated in the SAME process can panic with duplicate activation,
    // even though real nodes would restart in a fresh process. Close this DB
    // and load it from a fresh child binary (the very same test executable).
    if err:=db.Close();err!=nil {
        return fmt.Errorf("close first process chain database: %w",err)
    }
    self,err:=os.Executable()
    if err!=nil {return fmt.Errorf("resolve disposable executable: %w",err)}
    child:=exec.Command(self,"--verify-restart",dir)
    output,err:=child.CombinedOutput()
    if err!=nil {
        return fmt.Errorf("fresh OS process failed PRVI restart verification: %w\n%s",err,string(output))
    }
    fmt.Print(string(output))
    fmt.Println("PASS: two finalized blocks + full app restart in fresh process; capped PRVI unchanged")

    fmt.Println("PASS: actual customized Cosmos EVM app accepts a cap-compliant, in-memory, valueless positive genesis fixture")
    fmt.Println("NO FINANCIAL PRVI ISSUED, NO PUBLIC CHAIN, NO PRODUCTION KEYS")
    return nil
}
// In a fresh OS process, this runs the exact same pinned custom app over the
// temporary chain DB that has already committed two blocks. No InitChain call,
// key, cloud resource, external token or network is created by the child.
func verifyRestart(dir string) error {
    const chainID="privi-ci-only-not-financial-1"
    const expectedAPRVI="3000000000000000000"
    db,err:=dbm.NewGoLevelDB("privi-ephemeral",dir,nil)
    if err!=nil {return fmt.Errorf("reopen temporary chain database: %w",err)}
    defer db.Close()
    restarted:=evmd.NewExampleApp(log.NewNopLogger(),db,true,
        simtestutil.EmptyAppOptions{},baseapp.SetChainID(chainID))
    if restarted.LastBlockHeight()!=2 {
        return fmt.Errorf("restarted chain height changed: %d",restarted.LastBlockHeight())
    }
    ctx:=restarted.NewContextLegacy(true,cmtproto.Header{ChainID:chainID,Height:2})
    capState,err:=restarted.PriviCapKeeper.Snapshot(ctx)
    if err!=nil {return fmt.Errorf("cap state missing after app restart: %w",err)}
    if capState.GenesisBase!=expectedAPRVI||
        capState.LifetimeIssuedBase!=expectedAPRVI||
        capState.MintPolicy!="NO_NEW_NATIVE_PRVI_MINTS" {
        return fmt.Errorf("native issuance policy changed after restart: %+v",capState)
    }
    if supply:=restarted.BankKeeper.GetSupply(ctx,prvicap.BaseDenom).Amount.String();supply!=expectedAPRVI {
        return fmt.Errorf("restarted PRVI supply unexpectedly changed: %s",supply)
    }
    err=restarted.BankKeeper.MintCoins(ctx,minttypes.ModuleName,
        sdk.NewCoins(sdk.NewInt64Coin(prvicap.BaseDenom,1)))
    if !errors.Is(err,prvicap.ErrMintForbidden) {
        return fmt.Errorf("SECURITY: native mint allowed after process restart: %v",err)
    }
    fmt.Println("PASS: freshly restarted process loaded PRVI cap at height 2 and denied unauthorized mint")
    // Adversarial lifetime cap proof on the real SDK bank module:
    // physically BURN 1 native aprvi base unit via the x/vm module, then
    // attempt to MINT exactly that unit back. A supply <= original genesis
    // must never grant a fresh issuance allowance. This disposable
    // checkpoint uses the child process's check-state only; NO public
    // transaction, production key or financial PRVI exists.
    one:=sdk.NewCoins(sdk.NewInt64Coin(prvicap.BaseDenom,1))
    user:=sdk.AccAddress(bytes.Repeat([]byte{0x42},20))
    beforeBurn:=restarted.BankKeeper.GetSupply(ctx,prvicap.BaseDenom).Amount
    if err:=restarted.BankKeeper.SendCoinsFromAccountToModule(ctx,user,
        vmtypes.ModuleName,one);err!=nil {
        return fmt.Errorf("prepare disposable actual bank native burn: %w",err)
    }
    if err:=restarted.BankKeeper.BurnCoins(ctx,vmtypes.ModuleName,one);err!=nil {
        return fmt.Errorf("actual SDK bank native burn rejected: %w",err)
    }
    if afterBurn:=restarted.BankKeeper.GetSupply(ctx,prvicap.BaseDenom).Amount;
        !afterBurn.Equal(beforeBurn.Sub(sdkmath.NewInt(1))) {
        return fmt.Errorf("actual bank supply did not decrease on native burn")
    }
    if err:=restarted.PriviCapKeeper.Reconcile(ctx,restarted.BankKeeper);err!=nil {
        return fmt.Errorf("cap reconciliation rejected legitimate native burn: %w",err)
    }
    if err:=restarted.BankKeeper.MintCoins(ctx,vmtypes.ModuleName,one);
        !errors.Is(err,prvicap.ErrMintForbidden) {
        return fmt.Errorf("SECURITY: burn unlocked prohibited native re-mint: %v",err)
    }
    capAfterBurn,err:=restarted.PriviCapKeeper.Snapshot(ctx)
    if err!=nil || capAfterBurn!=capState {
        return fmt.Errorf("burn changed lifetime-issued cap: previous=%+v current=%+v error=%v",
            capState,capAfterBurn,err)
    }
    fmt.Println("PASS: real SDK native burn reduces supply but cannot unlock lifetime remint")

    return nil
}

func main() {
    if len(os.Args)==3 && os.Args[1]=="--verify-restart" {
        if err:=verifyRestart(os.Args[2]);err!=nil {
            fmt.Fprintln(os.Stderr,err);os.Exit(1)
        }
        return
    }
    if len(os.Args)!=1 {
        fmt.Fprintln(os.Stderr,"unexpected command-line args");os.Exit(2)
    }
    if err:=probe();err!=nil {fmt.Fprintln(os.Stderr,err);os.Exit(1)}
}
