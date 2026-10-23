// A deliberately valueless, deterministic *negative* InitChain probe.
// It invokes the customized evmd application, not a mocked cap keeper.
// This executable neither creates keys nor starts a network or issues PRVI.
package main

import (
    "crypto/ed25519"
    "crypto/rand"
    "encoding/json"
    "fmt"
    "math/big"
    "os"
    "os/exec"
    "strings"

    "cosmossdk.io/log/v2"
    sdkmath "cosmossdk.io/math"
    abci "github.com/cometbft/cometbft/abci/types"
    dbm "github.com/cosmos/cosmos-db"
    "github.com/cosmos/evm/evmd"
    "github.com/cosmos/evm/evmd/prvicap"
    prvipop "github.com/cosmos/evm/evmd/prvipop"
    srvflags "github.com/cosmos/evm/server/flags"
    "github.com/cosmos/cosmos-sdk/baseapp"
    simtestutil "github.com/cosmos/cosmos-sdk/testutil/sims"
    sdk "github.com/cosmos/cosmos-sdk/types"
    banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
)

// Synthetic, nonfinancial CI-only EIP-155 candidate; never a launch identity.
type priviTestAppOptions struct{}
func (priviTestAppOptions) Get(key string) interface{} {
    if key == srvflags.EVMChainID { return uint64(424242) }
    if key == "privi.pop.allow_unpinned_dev" { return true }
    return nil
}

// PoP fixture signers are disposable, in-memory Ed25519 test identities.
type probePoPGenesis struct {
    ChainID string `json:"chain_id"`
    Authorities []prvipop.Authority `json:"authorities"`
}

// Prepare a bank declaration within the cap and a structurally valid PoP
// registry, so the selected InitChain negative case reaches the intended
// guard instead of failing earlier on the upstream atest demo supply.
func validPoPAndBankFixture(app *evmd.EVMD,state map[string]json.RawMessage) error {
    var bank banktypes.GenesisState
    if err:=app.AppCodec().UnmarshalJSON(state[banktypes.ModuleName],&bank);err!=nil{return err}
    bank.Supply=sdk.NewCoins(sdk.NewInt64Coin(prvicap.BaseDenom,1))
    state[banktypes.ModuleName]=app.AppCodec().MustMarshalJSON(&bank)
    author,_,err:=ed25519.GenerateKey(rand.Reader)
    if err!=nil{return err}
    p:=probePoPGenesis{ChainID:"privi-valueless-genesis-probe-1",
        Authorities:[]prvipop.Authority{{Company:"TESTCO",Zone:"GRID/READINGS",PublicKey:author}}}
    raw,err:=json.Marshal(p)
    if err!=nil{return err}
    state[prvipop.StoreKey]=raw
    return nil
}
func mutatePoPFixture(app *evmd.EVMD,state map[string]json.RawMessage,
    mutate func(*probePoPGenesis)) error {
    if err:=validPoPAndBankFixture(app,state);err!=nil{return err}
    var p probePoPGenesis
    if err:=json.Unmarshal(state[prvipop.StoreKey],&p);err!=nil{return err}
    mutate(&p)
    raw,err:=json.Marshal(p)
    if err!=nil{return err}
    state[prvipop.StoreKey]=raw
    return nil
}

// Only the nonfinancial negative fixture; this must fail before a keeper or
// codec is constructed, rather than after InitChain has modified state.
type forbiddenEVMOptions struct{ id uint64 }
func (o forbiddenEVMOptions) Get(key string) interface{} {
    if key == srvflags.EVMChainID { return o.id }
    return nil
}
// No chain setup or private keys: the constructor must fail before EVM
// global fork configuration when any non-CI chain omits the PoP registry pin.
type unpinnedIdentityOptions struct{ id uint64; allow bool }
func (o unpinnedIdentityOptions) Get(key string) interface{} {
    if key == srvflags.EVMChainID { return o.id }
    if key == "privi.pop.allow_unpinned_dev" && o.allow { return true }
    return nil
}
func rejectUnpinnedStartup(id uint64,allow bool) (err error) {
    defer func() {
        caught:=recover()
        if caught==nil {
            err=fmt.Errorf("SECURITY: unpinned Privi chain accepted EVM ID %d allow=%v",id,allow)
        } else if !strings.Contains(fmt.Sprint(caught),"Privi PoP trusted registry digest REQUIRED") {
            err=fmt.Errorf("startup denied for unrelated reason: %v",caught)
        }
    }()
    _=evmd.NewExampleApp(log.NewNopLogger(),dbm.NewMemDB(),false,
        unpinnedIdentityOptions{id:id,allow:allow},
        baseapp.SetChainID("privi-valueless-genesis-probe-1"))
    return nil
}

func assertRejectEVMIdentityBeforeAppInit(id uint64) (err error) {
    defer func() {
        caught:=recover()
        if caught==nil {
            err=fmt.Errorf("SECURITY: Privi app accepted developer EIP-155 ID %d",id)
            return
        }
        if !strings.Contains(fmt.Sprint(caught),"PRVI EIP-155 app identity rejected") {
            err=fmt.Errorf("Privi app rejected EVM identity for unrelated reason: %v",caught)
        }
    }()
    _ = evmd.NewExampleApp(log.NewNopLogger(), dbm.NewMemDB(), false,
        forbiddenEVMOptions{id:id}, baseapp.SetChainID("privi-valueless-identity-probe-1"))
    return nil
}

func runCase(name string, mutate func(*evmd.EVMD, map[string]json.RawMessage) error, want string) error {
    // An upstream Cosmos EVM global chain configuration may be set only
    // once per OS process. Exactly ONE genesis test runs in each child.
    if os.Getenv("PRIVI_NEGATIVE_GENESIS_CASE") != name { return nil }
    // No chain keys or funded accounts are created in this process.
    app := evmd.NewExampleApp(log.NewNopLogger(), dbm.NewMemDB(), true,
        priviTestAppOptions{}, baseapp.SetChainID("privi-valueless-genesis-probe-1"))
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
    for _, id := range []uint64{0, 1, 56, 97, 1337, 31337, 4221, 262144} {
        if err:=assertRejectEVMIdentityBeforeAppInit(id);err!=nil {
            fmt.Fprintln(os.Stderr,err)
            os.Exit(1)
        }
    }
    fmt.Println("PASS: customized app constructor rejected 8 unsafe EIP-155 chain IDs")
    for _,tc:=range []struct{evm uint64; allow bool}{
        {424242,false}, {424243,false}, {424243,true},
    } {
        if err:=rejectUnpinnedStartup(tc.evm,tc.allow);err!=nil {
            fmt.Fprintln(os.Stderr,err)
            os.Exit(1)
        }
    }
    fmt.Println("PASS: unpinned PoP rejected outside explicitly valueless fixed CI")
    if os.Getenv("PRIVI_NEGATIVE_GENESIS_CASE") == "" {
        // The VM keeper sets process-global EVM chainConfig and panics
        // if a second app attempts to reset it. Use one fresh subprocess
        // per case; make every child's expected PASS marker mandatory.
        names:=[]string{
            "default upstream atest genesis",
            "declared PRVI over lifetime cap",
            "missing bank genesis module",
            "aprvi declaration with wrong EVM gas token",
            "missing PoP authorization registry",
            "malformed PoP authorization registry",
            "PoP authorization chain mismatch",
            "duplicate PoP position authority",
        }
        for _, name:=range names {
            child:=exec.Command(os.Args[0])
            child.Env=append(os.Environ(), "PRIVI_NEGATIVE_GENESIS_CASE="+name)
            output,err:=child.CombinedOutput()
            if err!=nil || !strings.Contains(string(output),"PASS "+name+":") {
                fmt.Fprintf(os.Stderr,"FAIL: isolated valueless genesis case %q: %v\n%s",name,err,string(output))
                os.Exit(1)
            }
            fmt.Print(string(output))
        }
        fmt.Println("ALL PASS: 8 isolated full-app valueless negative genesis cases; no network started")
        return
    }
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
        validPoPAndBankFixture,
        "PRVI native genesis: EVM gas denomination must be aprvi");err!=nil {
        fmt.Fprintln(os.Stderr,err);os.Exit(1)
    }
    // These four cases exercise the actual custom-node InitChain PoP checks,
    // not a standalone PoP keeper mock. All must reject BEFORE module writes.
    if err:=runCase("missing PoP authorization registry",
        func(app *evmd.EVMD,state map[string]json.RawMessage) error {
            if err:=validPoPAndBankFixture(app,state);err!=nil{return err}
            delete(state,prvipop.StoreKey)
            return nil
        },"Privi PoP genesis: authorization registry absent");err!=nil {
        fmt.Fprintln(os.Stderr,err);os.Exit(1)
    }
    if err:=runCase("malformed PoP authorization registry",
        func(app *evmd.EVMD,state map[string]json.RawMessage) error {
            if err:=validPoPAndBankFixture(app,state);err!=nil{return err}
            state[prvipop.StoreKey]=json.RawMessage(`"not-a-registry"`)
            return nil
        },"Privi PoP genesis: malformed authorization registry");err!=nil {
        fmt.Fprintln(os.Stderr,err);os.Exit(1)
    }
    if err:=runCase("PoP authorization chain mismatch",
        func(app *evmd.EVMD,state map[string]json.RawMessage) error {
            return mutatePoPFixture(app,state,func(p *probePoPGenesis){
                p.ChainID="privi-foreign-1"
            })
        },"Privi PoP genesis: Cosmos chain identity mismatch");err!=nil {
        fmt.Fprintln(os.Stderr,err);os.Exit(1)
    }
    if err:=runCase("duplicate PoP position authority",
        func(app *evmd.EVMD,state map[string]json.RawMessage) error {
            return mutatePoPFixture(app,state,func(p *probePoPGenesis){
                p.Authorities=append(p.Authorities,p.Authorities[0])
            })
        },"Privi PoP genesis: unsafe author registry before SDK InitGenesis");err!=nil {
        fmt.Fprintln(os.Stderr,err);os.Exit(1)
    }
    // A child process contains exactly one customized Cosmos EVM app; no
    // independent pass marker is emitted without the selected case passing.
}
