// A deliberately valueless, deterministic *negative* InitChain probe.
// It invokes the customized evmd application, not a mocked cap keeper.
// This executable neither creates keys nor starts a network or issues PRVI.
package main

import (
    "encoding/json"
    "fmt"
    "math/big"
    "os"
    "strings"

    "cosmossdk.io/log/v2"
    sdkmath "cosmossdk.io/math"
    abci "github.com/cometbft/cometbft/abci/types"
    dbm "github.com/cosmos/cosmos-db"
    "github.com/cosmos/evm/evmd"
    "github.com/cosmos/evm/evmd/prvicap"
    "github.com/cosmos/cosmos-sdk/baseapp"
    simtestutil "github.com/cosmos/cosmos-sdk/testutil/sims"
    sdk "github.com/cosmos/cosmos-sdk/types"
    banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
)

func runCase(name string, mutate func(*evmd.EVMD, map[string]json.RawMessage) error, want string) error {
    // No chain keys or funded accounts are created in this process.
    app := evmd.NewExampleApp(log.NewNopLogger(), dbm.NewMemDB(), true,
        simtestutil.EmptyAppOptions{}, baseapp.SetChainID("privi-valueless-genesis-probe-1"))
    state := app.DefaultGenesis()
    if mutate != nil {
        if err := mutate(app, state); err != nil {return fmt.Errorf("%s: fixture: %w", name, err)}
    }
    raw,err:=json.Marshal(state)
    if err!=nil {return fmt.Errorf("%s: marshal: %w",name,err)}
    _,err=app.InitChain(&abci.RequestInitChain{
        ChainId:"privi-valueless-genesis-probe-1",
        ConsensusParams:simtestutil.DefaultConsensusParams,
        AppStateBytes:raw,
    })
    if err==nil {return fmt.Errorf("%s: unsafe InitChain unexpectedly accepted prohibited genesis",name)}
    if !strings.Contains(err.Error(),want) {
        return fmt.Errorf("%s: InitChain refused for unrelated reason (wanted %q): %v",name,want,err)
    }
    fmt.Printf("PASS %s: customized full app InitChain refused before module genesis (%s)\n",name,want)
    return nil
}
func main() {
    // Default upstream demo uses atest and MUST NOT silently initialize
    // a proposed native aprvi financial chain.
    if err:=runCase("default upstream atest genesis",nil,
        "PRVI cap declared genesis denied before module init");err!=nil {
        fmt.Fprintln(os.Stderr,err);os.Exit(1)
    }
    // Even if a malicious/careless operator edits just the declared bank
    // supply, a quantity above 1B PRVI MUST stop before module initialization.
    badSupply:=func(app *evmd.EVMD,state map[string]json.RawMessage) error {
        var bank banktypes.GenesisState
        if err:=app.AppCodec().UnmarshalJSON(state[banktypes.ModuleName],&bank);err!=nil {return err}
        excessive,ok:=new(big.Int).SetString(prvicap.MaxBase,10)
        if !ok {return fmt.Errorf("invalid static cap")}
        excessive.Add(excessive,big.NewInt(1))
        bank.Supply=sdk.NewCoins(sdk.NewCoin(prvicap.BaseDenom,sdkmath.NewIntFromBigInt(excessive)))
        state[banktypes.ModuleName]=app.AppCodec().MustMarshalJSON(&bank)
        return nil
    }
    if err:=runCase("declared PRVI over lifetime cap",badSupply,
        "PRVI cap declared genesis denied before module init");err!=nil {
        fmt.Fprintln(os.Stderr,err);os.Exit(1)
    }
    if err:=runCase("missing bank genesis module",func(_ *evmd.EVMD,state map[string]json.RawMessage) error {
        delete(state,banktypes.ModuleName)
        return nil
    },"PRVI cap: bank genesis absent");err!=nil {
        fmt.Fprintln(os.Stderr,err);os.Exit(1)
    }
    // An aprvi balance or supply declaration alone cannot make a developer
    // EVM chain with upstream "stake" gas a legitimate Privi-native chain.
    if err:=runCase("aprvi declaration with wrong EVM gas token",
        func(app *evmd.EVMD,state map[string]json.RawMessage) error {
            var bank banktypes.GenesisState
            if err:=app.AppCodec().UnmarshalJSON(state[banktypes.ModuleName],&bank);err!=nil {return err}
            bank.Supply=sdk.NewCoins(sdk.NewInt64Coin(prvicap.BaseDenom,1))
            state[banktypes.ModuleName]=app.AppCodec().MustMarshalJSON(&bank)
            return nil
        },"PRVI native genesis: EVM gas denomination must be aprvi");err!=nil {
        fmt.Fprintln(os.Stderr,err);os.Exit(1)
    }
    fmt.Println("ALL PASS: 4 full-app valueless negative genesis cases; no network started")
}
