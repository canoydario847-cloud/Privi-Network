// A valueless *positive* customized Cosmos EVM InitChain test.
// This uses an ephemeral on-disk CI database and a disposable consensus test pubkey.
// A fresh child process opens the same DB to avoid upstream Cosmos EVM's
// process-global fork activation duplication on same-process app reconstruction.
// Never a production signer, deployable genesis or financial PRVI.
package main

import (
    "bytes"
    "crypto/ed25519"
    "crypto/rand"
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "math/big"
    "errors"
    "fmt"
    "os"
    "os/exec"
    "strings"
    "time"

    "cosmossdk.io/log/v2"
    sdkmath "cosmossdk.io/math"
    abci "github.com/cometbft/cometbft/abci/types"
    cmttypes "github.com/cometbft/cometbft/types"
    cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
    ethcommon "github.com/ethereum/go-ethereum/common"
    ethtypes "github.com/ethereum/go-ethereum/core/types"
    dbm "github.com/cosmos/cosmos-db"
    "github.com/cosmos/evm/evmd"
    "github.com/cosmos/evm/evmd/prvicap"
    evmtesttx "github.com/cosmos/evm/testutil/tx"
    cryptotypes "github.com/cosmos/cosmos-sdk/crypto/types"
    prvipop "github.com/cosmos/evm/evmd/prvipop"
    srvflags "github.com/cosmos/evm/server/flags"
    vmtypes "github.com/cosmos/evm/x/vm/types"
    erc20types "github.com/cosmos/evm/x/erc20/types"
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

// Synthetic, nonfinancial CI-only EIP-155 candidate; never a launch identity.
type priviTestAppOptions struct{}
func (priviTestAppOptions) Get(key string) interface{} {
    if key == srvflags.EVMChainID { return uint64(424242) }
    return nil
}

// This test manually invokes the custom application's post-execution hook
// with a synthetic EVM SDK message against REAL mounted native PoP state.
// It does NOT submit a signed EVM transaction through BaseApp FinalizeBlock;
// that complete ABCI transaction-routing test remains a separate launch gate.
func testNativePoPPostHook(app *evmd.EVMD,ctx sdk.Context,priv ed25519.PrivateKey) (string,error) {
    rawHash:=sha256.Sum256([]byte("disposable PoP telemetry on test app only"))
    p:=prvipop.Position{
        ChainID:"privi-ci-only-not-financial-1",Company:"UTQ4JJ20",Zone:"GRID/READINGS",
        Sequence:1,Stamp:"PoP:UTQ4JJ20:GRID/READINGS:000001",
        PriorHash:strings.Repeat("0",64),EventHash:hex.EncodeToString(rawHash[:]),
        Signer:append([]byte(nil),priv.Public().(ed25519.PublicKey)...),
    }
    signed,err:=prvipop.CanonicalMessage(p);if err!=nil{return "",err}
    p.Signature=ed25519.Sign(priv,signed)
    p.BlockHash,err=prvipop.SealedHash(p);if err!=nil{return "",err}
    wire,err:=prvipop.EncodeEnvelope(p);if err!=nil{return "",err}
    sink:=ethcommon.HexToAddress(prvipop.PoPSinkEVMAddress)
    makeSDKMsg:=func(to ethcommon.Address,value *big.Int,payload []byte)*vmtypes.MsgEthereumTx {
        tx:=ethtypes.NewTx(&ethtypes.LegacyTx{
            To:&to,Value:value,Gas:200000,GasPrice:big.NewInt(1),Data:payload,
        })
        m:=new(vmtypes.MsgEthereumTx)
        m.FromEthereumTx(tx)
        return m
    }
    tx:=makeSDKMsg(sink,big.NewInt(0),wire)
    finalCtx:=ctx.WithExecMode(sdk.ExecModeFinalize)
    if _,err=app.ApplyPriviPoPFromFinalizedTx(finalCtx,tx,false,false);err!=nil{
        return "",fmt.Errorf("failed EVM msg should be ignored: %w",err)
    }
    if _,err=app.ApplyPriviPoPFromFinalizedTx(finalCtx,tx,true,true);err!=nil{
        return "",fmt.Errorf("simulated EVM msg should be ignored: %w",err)
    }
    if seq,_,err:=app.PriviPoPKeeper.Snapshot(finalCtx,p.Company,p.Zone);err!=nil||seq!=0{
        return "",fmt.Errorf("failed/simulated PoP tx advanced consensus state: %v, seq %d",err,seq)
    }
    if _,err=app.ApplyPriviPoPFromFinalizedTx(finalCtx,makeSDKMsg(
        ethcommon.HexToAddress("0x00000000000000000000000000000000000000fe"),
        big.NewInt(0),wire),false,true);err!=nil{return "",err}
    if seq,_,err:=app.PriviPoPKeeper.Snapshot(finalCtx,p.Company,p.Zone);err!=nil||seq!=0{
        return "",fmt.Errorf("wrong EVM destination changed PoP consensus state: %v %d",err,seq)
    }
    if _,err=app.ApplyPriviPoPFromFinalizedTx(finalCtx,makeSDKMsg(
        sink,big.NewInt(1),wire),false,true);err==nil {
        return "",fmt.Errorf("PoP payment-value guard missing")
    }
    if _,err=app.ApplyPriviPoPFromFinalizedTx(finalCtx,makeSDKMsg(
        sink,big.NewInt(0),[]byte("not-a-position")),false,true);err==nil {
        return "",fmt.Errorf("noncanonical PoP payload accepted")
    }
    if _,err=app.ApplyPriviPoPFromFinalizedTx(finalCtx,tx,false,true);err!=nil {
        return "",fmt.Errorf("valid signed PoP native state transition denied: %w",err)
    }
    if seq,tip,err:=app.PriviPoPKeeper.Snapshot(finalCtx,p.Company,p.Zone);err!=nil||seq!=1||tip!=p.BlockHash {
        return "",fmt.Errorf("PoP posthandler did not persist accepted position: %d %s %v",seq,tip,err)
    }
    if _,err=app.ApplyPriviPoPFromFinalizedTx(finalCtx,tx,false,true);err==nil{
        return "",fmt.Errorf("PoP replay succeeded through native posthandler")
    }
    attacker:=p
    attacker.EventHash=strings.Repeat("f",64)
    forged,err:=prvipop.EncodeEnvelope(attacker);if err!=nil{return "",err}
    if _,err=app.ApplyPriviPoPFromFinalizedTx(finalCtx,makeSDKMsg(
        sink,big.NewInt(0),forged),false,true);err==nil {
        return "",fmt.Errorf("PoP forged-data envelope accepted")
    }
    if seq,tip,err:=app.PriviPoPKeeper.Snapshot(finalCtx,p.Company,p.Zone);err!=nil||seq!=1||tip!=p.BlockHash{
        return "",fmt.Errorf("failed or replayed PoP tx changed ledger: %d %s %v",seq,tip,err)
    }
    return p.BlockHash,nil
}

// signedABCIPosition encodes a REAL signed Ethereum message inside the pinned
// Cosmos EVM SDK Tx format; the caller submits these bytes via FinalizeBlock.
// Every key used here is ephemeral, CI-only and never reused by production.
func signedABCIPosition(app *evmd.EVMD,key cryptotypes.PrivKey,envelope []byte,nonce uint64)([]byte,error){
    sink:=ethcommon.HexToAddress(prvipop.PoPSinkEVMAddress)
    eth:=ethtypes.NewTx(&ethtypes.LegacyTx{
        Nonce:nonce,To:&sink,Value:big.NewInt(0),Gas:200000,
        GasPrice:big.NewInt(100000000000),Data:envelope,
    })
    msg:=new(vmtypes.MsgEthereumTx)
    msg.FromEthereumTx(eth)
    msg.From=key.PubKey().Address().Bytes()
    signed,err:=evmtesttx.PrepareEthTx(app.GetTxConfig(),key,msg)
    if err!=nil{return nil,fmt.Errorf("sign disposable PoP Ethereum tx: %w",err)}
    wire,err:=app.GetTxConfig().TxEncoder()(signed)
    if err!=nil{return nil,fmt.Errorf("encode signed disposable Ethereum SDK tx: %w",err)}
    return wire,nil
}
func nextPoPPosition(author ed25519.PrivateKey,sequence uint64,previous string)(prvipop.Position,error){
    event:=sha256.Sum256([]byte(fmt.Sprintf("CI-only signed FinalizeBlock position %d",sequence)))
    p:=prvipop.Position{ChainID:"privi-ci-only-not-financial-1",
        Company:"UTQ4JJ20",Zone:"GRID/READINGS",Sequence:sequence,
        Stamp:fmt.Sprintf("PoP:UTQ4JJ20:GRID/READINGS:%06d",sequence),
        PriorHash:previous,EventHash:hex.EncodeToString(event[:]),
        Signer:append([]byte(nil),author.Public().(ed25519.PublicKey)...),
    }
    body,err:=prvipop.CanonicalMessage(p)
    if err!=nil{return prvipop.Position{},err}
    p.Signature=ed25519.Sign(author,body)
    p.BlockHash,err=prvipop.SealedHash(p)
    return p,err
}
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
        priviTestAppOptions{}, baseapp.SetChainID(chainID))
    genesis := app.DefaultGenesis()

    // The built-in Cosmos SDK fixture provides the correct bonded-validator,
    // auth and bank genesis shape. Signing material is disposable in-memory CI.
    pv := mock.NewPV()
    pubKey, err := pv.GetPubKey()
    if err != nil {return fmt.Errorf("ephemeral mock pubkey: %w",err)}
    validators := cmttypes.NewValidatorSet([]*cmttypes.Validator{cmttypes.NewValidator(pubKey, 1)})
    address := sdk.AccAddress(bytes.Repeat([]byte{0x42},20))
    account := authtypes.NewBaseAccount(address,nil,0,0)
    evmAddr,evmPriv:=evmtesttx.NewAccAddressAndKey()
    if evmPriv==nil{return fmt.Errorf("ephemeral EVM signing key unavailable")}
    evmAccount:=authtypes.NewBaseAccount(evmAddr,evmPriv.PubKey(),0,0)
    allocation := sdk.NewCoins(
        sdk.NewCoin(prvicap.BaseDenom,sdkmath.NewInt(1_000_000_000_000_000_000)),
    )
    bal := banktypes.Balance{Address: account.GetAddress().String(), Coins: allocation}
    evmFunding:=sdk.NewCoins(sdk.NewCoin(prvicap.BaseDenom,sdkmath.NewInt(1_000_000_000_000_000_000)))
    signedEvmBal:=banktypes.Balance{Address:evmAccount.GetAddress().String(),Coins:evmFunding}
    genesis, err = simtestutil.GenesisStateWithValSet(
        app.AppCodec(), genesis, validators,
        []authtypes.GenesisAccount{account,evmAccount}, bal,signedEvmBal,
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
    // Test the real customized InitChain fail-closed gate on two distinct
    // attempts to reintroduce native issuance. Each test uses a fresh
    // valueless app process; no PRVI tokens or production state are created.
    mintNegativeMode:=os.Getenv("PRIVI_MINT_NEGATIVE_PROBE")
    switch mintNegativeMode {
    case "":
    case "inflation":
        mintGenesis.Params.InflationMax=sdkmath.LegacyOneDec()
    case "provisions":
        mintGenesis.Minter.AnnualProvisions=sdkmath.LegacyOneDec()
    default:
        return fmt.Errorf("unrecognized valueless mint negative mode")
    }
    genesis[minttypes.ModuleName]=app.AppCodec().MustMarshalJSON(&mintGenesis)
    // The upstream reference defaults ERC20 registration to permissionless.
    // Privi's native-denom genesis must opt out before InitChain begins.
    var erc20Genesis erc20types.GenesisState
    if err:=app.AppCodec().UnmarshalJSON(genesis[erc20types.ModuleName], &erc20Genesis);err!=nil {
        return fmt.Errorf("read valueless ERC20 module fixture: %w",err)
    }
    erc20Genesis.Params.PermissionlessRegistration=false
    // Each adversarial case uses a distinct ephemeral OS process, so
    // Cosmos EVM process-global fork registration cannot invalidate results.
    erc20NegativeMode:=os.Getenv("PRIVI_ERC20_NEGATIVE_PROBE")
    switch erc20NegativeMode {
    case "":
    case "permissionless":
        erc20Genesis.Params.PermissionlessRegistration=true
    case "native-pair":
        erc20Genesis.TokenPairs=append(erc20Genesis.TokenPairs,
            erc20types.TokenPair{
                Denom:prvicap.BaseDenom,
                Erc20Address:"0x00000000000000000000000000000000000000ee",
                Enabled:false,
                ContractOwner:erc20types.OWNER_MODULE,
            })
    default:
        return fmt.Errorf("unrecognized valueless ERC20 negative mode")
    }
    // Only the positive fixture must be free of native conversion pairs.
    // Negative fixtures deliberately inject an unsafe pair and must reach
    // the real app's InitChain rejection logic below.
    if erc20NegativeMode=="" {
        for _, pair:=range erc20Genesis.TokenPairs {
            if pair.Denom==prvicap.BaseDenom {
                return fmt.Errorf("positive fixture incorrectly maps native aprvi ERC20")
            }
        }
    }
    genesis[erc20types.ModuleName]=app.AppCodec().MustMarshalJSON(&erc20Genesis)
    // Bootstrap the native candidate PoP authorization registry with a
    // throwaway Ed25519 public key. This is NOT a production signing key,
    // network operator identity, PoP finality proof or launched token.
    popPub,popPriv,err:=ed25519.GenerateKey(rand.Reader)
    if err!=nil{return fmt.Errorf("disposable PoP author fixture: %w",err)}
    popGenesis:=struct {
        ChainID string `json:"chain_id"`
        Authorities []prvipop.Authority `json:"authorities"`
    }{
        ChainID:chainID,
        Authorities:[]prvipop.Authority{{
            Company:"UTQ4JJ20", Zone:"GRID/READINGS", PublicKey:popPub,
        }},
    }
    popNegativeMode:=os.Getenv("PRIVI_POP_NEGATIVE_PROBE")
    switch popNegativeMode {
    case "":
    case "wrong-chain":
        popGenesis.ChainID="privi-ci-incorrect"
    case "invalid-author":
        popGenesis.Authorities[0].PublicKey=nil
    case "missing":
    default:
        return fmt.Errorf("unknown disposable PoP genesis negative mode")
    }
    if popNegativeMode!="missing" {
        popBytes,marshalErr:=json.Marshal(popGenesis)
        if marshalErr!=nil{return marshalErr}
        genesis[prvipop.StoreKey]=popBytes
    }
    raw, err := json.Marshal(genesis)
    if err!=nil {return fmt.Errorf("encode custom genesis fixture: %w",err)}
    resp, err := app.InitChain(&abci.RequestInitChain{
        ChainId:chainID,
        ConsensusParams:simtestutil.DefaultConsensusParams,
        AppStateBytes:raw,
    })
    if popNegativeMode!="" {
        expected:="Privi PoP genesis:"
        if err==nil || !strings.Contains(err.Error(),expected){
            return fmt.Errorf("SECURITY: invalid PoP genesis accepted or wrong error: %v",err)
        }
        fmt.Printf("PASS: customized InitChain rejects unsafe PoP authorization genesis: %s\n",popNegativeMode)
        return nil
    }
    if mintNegativeMode!="" {
        expected:="PRVI native genesis: mint must target aprvi with ZERO inflation and provisions"
        if err==nil || !strings.Contains(err.Error(),expected) {
            return fmt.Errorf("SECURITY: invalid native mint fixture not rejected by correct InitChain rule: %v",err)
        }
        fmt.Printf("PASS: actual customized InitChain rejects unsafe native mint fixture: %s\n",mintNegativeMode)
        return nil
    }
    if erc20NegativeMode!="" {
        expected:="PRVI native genesis: permissionless ERC20 registration forbidden"
        if erc20NegativeMode=="native-pair" {
            expected="PRVI native genesis: aprvi ERC20 token pair forbidden"
        }
        if err==nil || !strings.Contains(err.Error(),expected) {
            return fmt.Errorf("SECURITY: invalid ERC20 fixture not rejected by correct InitChain rule: %v",err)
        }
        fmt.Printf("PASS: actual customized InitChain rejects unsafe ERC20 fixture: %s\n",erc20NegativeMode)
        return nil
    }
    if err!=nil {return fmt.Errorf("customized app InitChain rejected valid fixture: %w",err)}
    if resp==nil {return fmt.Errorf("nil InitChain response")}
    // Verify the REAL mounted, consensus-backed Privi cap keeper reads the
    // exact in-memory initial aprvi supply, and the FULL bank keeper injected
    // into the custom app refuses any post-genesis native mint operation.
    const expectedAPRVI = "3000000000000000000" // 3 valueless PRVI; NOT mainnet
    ctx := app.NewContextLegacy(false,cmtproto.Header{ChainID:chainID,Height:0})
    popSeq,popTip,popErr:=app.PriviPoPKeeper.Snapshot(ctx,"UTQ4JJ20","GRID/READINGS")
    if popErr!=nil||popSeq!=0||popTip!=strings.Repeat("0",64) {
        return fmt.Errorf("native PoP genesis signer registry not persisted: %d %s %v",popSeq,popTip,popErr)
    }
    fmt.Println("PASS: custom InitChain mounted and initialized native PoP authorization consensus KV store")
    verifiedPositionTip,err:=testNativePoPPostHook(app,ctx,popPriv)
    if err!=nil{return fmt.Errorf("native post-execution PoP state test: %w",err)}
    fmt.Printf("PASS: native PoP posthook accepted signed position and denied failed/replayed/forged calldata (tip=%s)\n",verifiedPositionTip)

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

    // Adversarial runtime mutation on a disposable in-memory app: prove an
    // x/erc20 params change would block the application's BeginBlock BEFORE
    // any standard module BeginBlock runs. Restore the fixture afterward.
    if err:=app.CheckPriviNativeERC20Invariant(ctx);err!=nil {
        return fmt.Errorf("positive ERC20 runtime invariant failed: %w",err)
    }
    // Mutations from normal keeper APIs must fail *before* any state write.
    if err:=app.Erc20Keeper.SetPermissionlessRegistration(ctx,true);err==nil {
        return fmt.Errorf("SECURITY: direct permissionless ERC20 setter accepted")
    }
    illegalParams:=app.Erc20Keeper.GetParams(ctx)
    illegalParams.PermissionlessRegistration=true
    if err:=app.Erc20Keeper.SetParams(ctx,illegalParams);err==nil {
        return fmt.Errorf("SECURITY: governance-style SetParams enabled permissionless ERC20")
    }
    if err:=app.CheckPriviNativeERC20Invariant(ctx);err!=nil {
        return fmt.Errorf("blocked permissionless change nevertheless modified state: %w",err)
    }
    // Simulate a privileged raw-store migration bypassing the patched setter.
    // Block-entry invariant must still catch this before module execution.
    erc20Store:=ctx.KVStore(app.GetKey(erc20types.StoreKey))
    erc20Store.Set(erc20types.ParamStoreKeyPermissionlessRegistration,[]byte("0x01"))
    _,beginErr:=app.BeginBlocker(ctx)
    if beginErr==nil || !strings.Contains(beginErr.Error(),
        "PRVI beginning-of-block ERC20 check denied") {
        return fmt.Errorf("SECURITY: raw permissionless ERC20 runtime change not denied by BeginBlock: %v",beginErr)
    }
    erc20Store.Delete(erc20types.ParamStoreKeyPermissionlessRegistration)
    if err:=app.CheckPriviNativeERC20Invariant(ctx);err!=nil {
        return fmt.Errorf("restored ERC20 registration check failed: %w",err)
    }

    // Insert a DISABLED native pair directly into the pinned SDK ERC20
    // keeper to simulate an unauthorized runtime/governance state change.
    // Deliberately bypass normal SetToken registration to test the
    // consensus store iterator, even if the denom lookup index is missing.
    injected:=erc20types.TokenPair{
        Denom:prvicap.BaseDenom,
        Erc20Address:"0x00000000000000000000000000000000000000f1",
        Enabled:false, ContractOwner:erc20types.OWNER_MODULE,
    }
    // Both public and lower-level keeper mutators deny native APRVI, even
    // when a caller attempts to register a disabled pair or only a denom map.
    if err:=app.Erc20Keeper.SetToken(ctx,injected);err==nil {
        return fmt.Errorf("SECURITY: SetToken allowed native aprvi")
    }
    if err:=app.Erc20Keeper.SetTokenPair(ctx,injected);err==nil {
        return fmt.Errorf("SECURITY: low-level SetTokenPair allowed native aprvi")
    }
    if err:=app.Erc20Keeper.SetDenomMap(ctx,prvicap.BaseDenom,injected.GetID());err==nil {
        return fmt.Errorf("SECURITY: low-level SetDenomMap allowed native aprvi")
    }
    if err:=app.CheckPriviNativeERC20Invariant(ctx);err!=nil {
        return fmt.Errorf("denied direct native pair mutations modified state: %w",err)
    }
    // A trusted BUT compromised upgrade could write raw ERC20 KV state.
    // This intentionally bypasses every keeper setter in ephemeral CI.
    pairKey:=append(append([]byte{},erc20types.KeyPrefixTokenPair...),injected.GetID()...)
    erc20Store.Set(pairKey,app.AppCodec().MustMarshal(&injected))
    _,beginErr=app.BeginBlocker(ctx)
    if beginErr==nil || !strings.Contains(beginErr.Error(),
        "PRVI beginning-of-block ERC20 check denied") {
        return fmt.Errorf("SECURITY: raw native APRVI token pair not denied by BeginBlock: %v",beginErr)
    }
    erc20Store.Delete(pairKey)
    if err:=app.CheckPriviNativeERC20Invariant(ctx);err!=nil {
        return fmt.Errorf("restored ERC20 token-pair state invalid: %w",err)
    }
    fmt.Println("PASS: actual customized BeginBlock denies ERC20 permissionless activation and native APRVI token-pair insertion")

    // Validate the *actual customized EVMD* has injected the module-facing
    // bank capability guard, rather than merely running unit tests against
    // the wrapper type. The direct unsafe native write must fail before it
    // can change any account or supply data.
    original:=app.BankKeeper.GetBalance(ctx,address,prvicap.BaseDenom)
    err=app.BankKeeper.UncheckedSetBalance(ctx,address,
        sdk.NewCoin(prvicap.BaseDenom,original.Amount.Add(sdkmath.NewInt(1))))
    if !errors.Is(err,prvicap.ErrDirectNativeBalanceForbidden) {
        return fmt.Errorf("SECURITY: custom app module-facing bank allowed unsafe native PRVI account write: %v",err)
    }
    if actual:=app.BankKeeper.GetBalance(ctx,address,prvicap.BaseDenom);!actual.IsEqual(original) {
        return fmt.Errorf("SECURITY: denied native account mutation modified actual balance: before=%s after=%s",original,actual)
    }
    if err:=app.PriviCapKeeper.Reconcile(ctx,app.BankKeeper);err!=nil {
        return fmt.Errorf("denied native account mutation modified bank supply: %w",err)
    }
    fmt.Println("PASS: actual customized app bank keeper rejects external native balance forgery BEFORE SDK storage writes")


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
    // REAL Ethereum ECDSA signature -> encoded Cosmos SDK Tx ->
    // BaseApp FinalizeBlock -> app PostHandler -> PoP consensus KV transition.
    // A direct post-handler test above is not a substitute for this path.
    pos2,err:=nextPoPPosition(popPriv,2,verifiedPositionTip)
    if err!=nil{return err}
    signedPayload,err:=prvipop.EncodeEnvelope(pos2)
    if err!=nil{return err}
    signedTxBytes,err:=signedABCIPosition(app,evmPriv,signedPayload,0)
    if err!=nil{return err}
    fin2,err:=app.FinalizeBlock(&abci.RequestFinalizeBlock{
        Height:2, Time:blockTime.Add(time.Second),
        DecidedLastCommit:abci.CommitInfo{Votes:votes},
        NextValidatorsHash:validators.Hash(),
        ProposerAddress:validators.Proposer.Address,
        Hash:app.LastCommitID().Hash,
        Txs:[][]byte{signedTxBytes},
    })
    if err!=nil {return fmt.Errorf("signed PoP FinalizeBlock height 2: %w",err)}
    if fin2==nil||len(fin2.TxResults)!=1 {
        return fmt.Errorf("signed PoP block must produce exactly one EVM transaction receipt")
    }
    if fin2.TxResults[0].Code!=0 {
        return fmt.Errorf("signed Ethereum PoP FinalizeBlock rejected: code=%d log=%s",
            fin2.TxResults[0].Code,fin2.TxResults[0].Log)
    }
    if _,err=app.Commit();err!=nil{return fmt.Errorf("commit signed PoP block: %w",err)}
    afterSigned:=app.NewContextLegacy(true,cmtproto.Header{ChainID:chainID,Height:2})
    seq,tip,err:=app.PriviPoPKeeper.Snapshot(afterSigned,"UTQ4JJ20","GRID/READINGS")
    if err!=nil||seq!=2||tip!=pos2.BlockHash {
        return fmt.Errorf("signed EVM FinalizeBlock did not persist position 2: %d %s %v",seq,tip,err)
    }
    fmt.Println("PASS: real signed Ethereum PoP calldata executed in BaseApp FinalizeBlock and committed native sequence 2")

    // A separately signed, correctly nonce-incremented EVM transaction
    // attempts to replay the already-finalized PoP position. The block must
    // finalize while the transaction fails and cannot advance the PoP ledger.
    replayBytes,err:=signedABCIPosition(app,evmPriv,signedPayload,1)
    if err!=nil{return err}
    fin3,err:=app.FinalizeBlock(&abci.RequestFinalizeBlock{
        Height:3,Time:blockTime.Add(2*time.Second),
        DecidedLastCommit:abci.CommitInfo{Votes:votes},
        NextValidatorsHash:validators.Hash(),
        ProposerAddress:validators.Proposer.Address,
        Hash:app.LastCommitID().Hash,
        Txs:[][]byte{replayBytes},
    })
    if err!=nil{return fmt.Errorf("replay-negative block FinalizeBlock: %w",err)}
    if fin3==nil||len(fin3.TxResults)!=1||fin3.TxResults[0].Code==0 {
        return fmt.Errorf("SECURITY: replayed PoP position was accepted as a valid EVM transaction")
    }
    if _,err=app.Commit();err!=nil{return fmt.Errorf("commit replay-negative block: %w",err)}
    afterReplay:=app.NewContextLegacy(true,cmtproto.Header{ChainID:chainID,Height:3})
    seq,tip,err=app.PriviPoPKeeper.Snapshot(afterReplay,"UTQ4JJ20","GRID/READINGS")
    if err!=nil||seq!=2||tip!=pos2.BlockHash {
        return fmt.Errorf("SECURITY: replayed PoP advanced committed position: %d %s %v",seq,tip,err)
    }
    if app.LastBlockHeight()!=3 {
        return fmt.Errorf("expected three persisted blocks, got %d",app.LastBlockHeight())
    }
    fmt.Println("PASS: separately signed PoP replay transaction rejected in real ABCI FinalizeBlock")


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
    fmt.Println("PASS: three finalized blocks + full app restart in fresh process; native PRVI issuance cap unchanged")

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
        priviTestAppOptions{},baseapp.SetChainID(chainID))
    if restarted.LastBlockHeight()!=3 {
        return fmt.Errorf("restarted chain height changed: %d",restarted.LastBlockHeight())
    }
    ctx:=restarted.NewContextLegacy(true,cmtproto.Header{ChainID:chainID,Height:3})
    popSeq,popTip,popErr:=restarted.PriviPoPKeeper.Snapshot(ctx,"UTQ4JJ20","GRID/READINGS")
    if popErr!=nil||popSeq!=2||popTip==strings.Repeat("0",64) {
        return fmt.Errorf("restarted PoP signed position or registry missing: %d %s %v",popSeq,popTip,popErr)
    }
    fmt.Println("PASS: ABCI-signed native PoP position checkpoint survived three commits and restart")
    capState,err:=restarted.PriviCapKeeper.Snapshot(ctx)
    if err!=nil {return fmt.Errorf("cap state missing after app restart: %w",err)}
    if capState.GenesisBase!=expectedAPRVI||
        capState.LifetimeIssuedBase!=expectedAPRVI||
        capState.MintPolicy!="NO_NEW_NATIVE_PRVI_MINTS" {
        return fmt.Errorf("native issuance policy changed after restart: %+v",capState)
    }
    if supply:=restarted.BankKeeper.GetSupply(ctx,prvicap.BaseDenom).Amount;
        !supply.IsPositive()||supply.GT(sdkmath.NewInt(3_000_000_000_000_000_000)) {
        return fmt.Errorf("restarted PRVI supply exceeded lifetime cap or became nonpositive: %s",supply)
    }
    err=restarted.BankKeeper.MintCoins(ctx,minttypes.ModuleName,
        sdk.NewCoins(sdk.NewInt64Coin(prvicap.BaseDenom,1)))
    if !errors.Is(err,prvicap.ErrMintForbidden) {
        return fmt.Errorf("SECURITY: native mint allowed after process restart: %v",err)
    }
    fmt.Println("PASS: freshly restarted process loaded PRVI cap at height 3 and denied unauthorized mint")
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
