// A valueless *positive* customized Cosmos EVM InitChain test.
// This uses an in-memory DB and an ephemeral consensus test pubkey;
// never a real validator signer, deployable genesis, or financial PRVI.
package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "os"

    "cosmossdk.io/log/v2"
    sdkmath "cosmossdk.io/math"
    abci "github.com/cometbft/cometbft/abci/types"
    cmttypes "github.com/cometbft/cometbft/types"
    dbm "github.com/cosmos/cosmos-db"
    "github.com/cosmos/evm/evmd"
    "github.com/cosmos/evm/evmd/prvicap"
    vmtypes "github.com/cosmos/evm/x/vm/types"
    "github.com/cosmos/cosmos-sdk/baseapp"
    simtestutil "github.com/cosmos/cosmos-sdk/testutil/sims"
    sdk "github.com/cosmos/cosmos-sdk/types"
    authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
    banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
    "github.com/cosmos/cosmos-sdk/testutil/mock"
)

func probe() error {
    const chainID = "privi-ci-only-not-financial-1"
    app := evmd.NewExampleApp(log.NewNopLogger(), dbm.NewMemDB(), true,
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
        sdk.NewCoin(prvicap.BaseDenom,sdkmath.NewInt(1_000_000_000_000_000_000)),
        sdk.NewCoin(vmtypes.DefaultEVMExtendedDenom,sdkmath.NewInt(100_000_000_000_000_000)),
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
    raw, err := json.Marshal(genesis)
    if err!=nil {return fmt.Errorf("encode custom genesis fixture: %w",err)}
    resp, err := app.InitChain(&abci.RequestInitChain{
        ChainId:chainID,
        ConsensusParams:simtestutil.DefaultConsensusParams,
        AppStateBytes:raw,
    })
    if err!=nil {return fmt.Errorf("customized app InitChain rejected valid fixture: %w",err)}
    if resp==nil {return fmt.Errorf("nil InitChain response")}
    fmt.Println("PASS: actual customized Cosmos EVM app accepts a cap-compliant, in-memory, valueless positive genesis fixture")
    fmt.Println("NO FINANCIAL PRVI ISSUED, NO PUBLIC CHAIN, NO PRODUCTION KEYS")
    return nil
}
func main() {
    if err:=probe();err!=nil {fmt.Fprintln(os.Stderr,err);os.Exit(1)}
}
