#!/usr/bin/env python3
"""Emit a REVIEW-ONLY Cosmos EVM v0.7.3 Privi source patch from a clean pinned checkout.

This does not change source, mint coins, generate genesis, run nodes or deploy.
The suggested code requires independent audit and real build/integration tests.
"""
import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

PIN = "c3ae9067a7eadcdea55a5192226916deb44c71c4"
MAX_BASE = "1000000000000000000000000000"
DEMO_IDS = {262144, 4221, 56, 97, 1, 31337, 1337}

class UnsafeInput(ValueError):
    pass

def checked_replace(data, old, new, path):
    n = data.count(old)
    if n != 1:
        raise UnsafeInput(f"{path}: expected ONE source anchor {old!r}, found {n}; upstream changed")
    return data.replace(old, new, 1)

def validated_settings(config):
    if config.get("status") != "DESIGN_ONLY_NOT_A_GENESIS":
        raise UnsafeInput("Only design-stage input is accepted")
    if config.get("source",{}).get("commit") != PIN:
        raise UnsafeInput("Pinned Cosmos EVM upstream commit mismatch")
    coin = config.get("coin",{})
    evm = config.get("evm",{})
    info = evm.get("coin_info",{})
    if (coin.get("display_denom") != "PRVI" or coin.get("base_denom") != "aprvi"
            or coin.get("decimals") != 18 or coin.get("max_supply_base_units") != MAX_BASE
            or coin.get("inflation_enabled") is not False
            or coin.get("mint_module_begin_block_enabled") is not False
            or info != {"denom":"aprvi","extended_denom":"aprvi","display_denom":"prvi","decimals":18}):
        raise UnsafeInput("Only approved PRVI fixed-supply atto-denom design is allowed")
    n = config.get("network",{})
    cid = n.get("cosmos_chain_id")
    eid = n.get("evm_chain_id")
    if not isinstance(cid,str) or not re.fullmatch("[a-z][a-z0-9-]{2,63}",cid) or cid.startswith(("local-","privi-dev")):
        raise UnsafeInput("Fresh reviewed production Cosmos chain ID is REQUIRED")
    if type(eid) is not int or eid < 1000 or eid in DEMO_IDS or eid > 4294967295:
        raise UnsafeInput("Fresh reviewed EVM numeric chain ID is REQUIRED; no default/test/BNB IDs")
    if n.get("demo_genesis_reuse_permitted") is not False:
        raise UnsafeInput("Demo genesis re-use prohibited")
    if config.get("constraints",{}).get("no_mainnet_deploy_or_mint") is not True:
        raise UnsafeInput("Design stage must prohibit launch")
    return cid,eid

def source_overlay(files, evm_chain_id):
    """Pure in-memory source patch; each anchor must match exact reviewed upstream code."""
    required = ("evmd/config/bech32.go","evmd/genesis.go",
                "evmd/cmd/evmd/cmd/root.go","evmd/app.go")
    for path in required:
        if path not in files:
            raise UnsafeInput(f"Missing upstream source {path}")
    result=dict(files)
    p="evmd/config/bech32.go"
    result[p] = checked_replace(result[p], 'Bech32Prefix = "cosmos"',
                                'Bech32Prefix = "privi"', p)
    p="evmd/cmd/evmd/cmd/root.go"
    x=result[p]
    x=checked_replace(x,'\t"github.com/cosmos/evm/x/vm/types"\n','',p)
    x=checked_replace(x,'config.InitAppConfig(types.DefaultEVMExtendedDenom, types.DefaultEVMChainID)',
                      f'config.InitAppConfig("aprvi", {evm_chain_id})',p)
    # SDK genutil InitCmd consumes BasicModuleManager.DefaultGenesis,
    # not EVMD.DefaultGenesis(). Without this adapter 'evmd init' silently
    # regenerates upstream denominations and inflation despite source patches.
    x=checked_replace(x,'\t"errors"\n','\t"encoding/json"\n\t"errors"\n',p)
    x=checked_replace(x,'\t"github.com/cosmos/cosmos-sdk/baseapp"\n',
                      '\t"github.com/cosmos/cosmos-sdk/baseapp"\n'
                      '\t"github.com/cosmos/cosmos-sdk/codec"\n'
                      '\t"github.com/cosmos/cosmos-sdk/types/module"\n',p)
    x=checked_replace(x,'// NewRootCmd creates a new root command for evmd. It is called once in the',
        'type priviInitGenesisBasic struct {\n'
        '\tmodule.AppModuleBasic\n'
        '\tmodule.HasGenesisBasics\n'
        '\tgenesis json.RawMessage\n'
        '}\n'
        'func (b priviInitGenesisBasic) DefaultGenesis(_ codec.JSONCodec) json.RawMessage { return b.genesis }\n'
        '// priviInitBasics makes the init CLI use the SAME reviewed genesis as EVMD.DefaultGenesis.\n'
        'func priviInitBasics(app *evmd.EVMD) module.BasicManager {\n'
        '\tdefaults := app.DefaultGenesis()\n'
        '\tresult := make(module.BasicManager, len(app.BasicModuleManager))\n'
        '\tfor name, basic := range app.BasicModuleManager {\n'
        '\t\t// SDK genutil InitCmd asserts concrete genutil.AppModuleBasic; do not wrap it.\n'
        '\t\tif name != "bank" && name != "mint" && name != "staking" && name != "evm" && name != "erc20" && name != "feemarket" {\n'
        '\t\t\tresult[name] = basic; continue\n'
        '\t\t}\n'
        '\t\tgen, ok := defaults[name]\n'
        '\t\tif !ok { result[name] = basic; continue }\n'
        '\t\thas, ok := basic.(module.HasGenesisBasics)\n'
        '\t\tif !ok { panic("Privi genesis module default mismatch: " + name) }\n'
        '\t\tresult[name] = priviInitGenesisBasic{AppModuleBasic: basic, HasGenesisBasics: has, genesis: gen}\n'
        '\t}\n'
        '\treturn result\n'
        '}\n\n'
        '// NewRootCmd creates a new root command for evmd. It is called once in the',p)
    x=checked_replace(x,'defaultNodeHome := config.MustGetDefaultNodeHome()\n',
       'defaultNodeHome := config.MustGetDefaultNodeHome()\n\tpriviBasics := priviInitBasics(evmApp)\n',p)
    x=checked_replace(x,
       'genutilcli.InitCmd(evmApp.BasicModuleManager, defaultNodeHome)',
       'genutilcli.InitCmd(priviBasics, defaultNodeHome)',p)
    x=checked_replace(x,
       'genutilcli.Commands(evmApp.TxConfig(), evmApp.BasicModuleManager, defaultNodeHome)',
       'genutilcli.Commands(evmApp.TxConfig(), priviBasics, defaultNodeHome)',p)
    result[p]=x

    p="evmd/genesis.go"
    x=result[p]
    x=checked_replace(x,
        "evmGenState := evmtypes.DefaultGenesisState()",
        'evmGenState := evmtypes.DefaultGenesisState()\n'
        '\tevmGenState.Params.EvmDenom = "aprvi"\n'
        '\tevmGenState.Params.ExtendedDenomOptions = &evmtypes.ExtendedDenomOptions{ExtendedDenom: "aprvi"}',p)
    x=checked_replace(x,'erc20GenState.TokenPairs = testconstants.ExampleTokenPairs',
                      'erc20GenState.TokenPairs = nil',p)
    x=checked_replace(x,'erc20GenState.NativePrecompiles = []string{testconstants.WEVMOSContractMainnet}',
                      'erc20GenState.NativePrecompiles = nil',p)
    x=checked_replace(x,'mintGenState.Params.MintDenom = testconstants.ExampleAttoDenom',
                      'mintGenState.Params.MintDenom = "aprvi"\n\tmintGenState.Minter.Inflation = sdkmath.LegacyZeroDec()',p)
    x=checked_replace(x, '\t"encoding/json"\n', '\t"encoding/json"\n\tsdkmath "cosmossdk.io/math"\n',p)
    x=checked_replace(x,'feeMarketGenState.Params.NoBaseFee = true',
                      'feeMarketGenState.Params.NoBaseFee = false',p)
    x=checked_replace(x,'\ttestconstants "github.com/cosmos/evm/testutil/constants"\n','',p)
    result[p]=x

    # Fail the ACTUAL financial chain InitChain if PRVI is not exactly the
    # one-billion-coin genesis allocation. The synthetic CI 'evmd init'
    # command only writes unfunded JSON and does not call InitChainer.
    # Post-genesis burns are allowed, but any supply above cap remains
    # independently rejected in EndBlocker.
    p="evmd/app.go"
    x=result[p]
    x=checked_replace(x,
        '\treturn app.ModuleManager.InitGenesis(ctx, app.appCodec, genesisState)\n}',
        '\tresponse, err := app.ModuleManager.InitGenesis(ctx, app.appCodec, genesisState)\n'
        '\tif err != nil { return response, err }\n'
        f'\tgenesisCap, ok := sdkmath.NewIntFromString("{MAX_BASE}")\n'
        '\tif !ok { return response, fmt.Errorf("invalid Privi genesis cap") }\n'
        '\tif !app.BankKeeper.GetSupply(ctx, "aprvi").Amount.Equal(genesisCap) {\n'
        '\t\treturn response, fmt.Errorf("Privi genesis native supply must equal exactly 1 billion PRVI")\n'
        '\t}\n'
        '\treturn response, nil\n}',p)
    # Enforce the EXACT bank genesis supply from the proposed JSON BEFORE
    # the Cosmos SDK initializes other modules (staking rejects empty
    # validator sets before the former post-InitGenesis supply check).
    # Retain post-initialization bank state check as a second safety barrier.
    x=checked_replace(x,
        '\\tif err := app.UpgradeKeeper.SetModuleVersionMap(ctx, app.ModuleManager.GetVersionMap()); err != nil {',
        '\\trawBankGenesis, present := genesisState[banktypes.ModuleName]\\n'
        '\\tif !present { return nil, fmt.Errorf("missing Privi bank genesis") }\\n'
        '\\tvar bankGenesis banktypes.GenesisState\\n'
        '\\tif err := app.appCodec.UnmarshalJSON(rawBankGenesis, &bankGenesis); err != nil {\\n'
        '\\t\\treturn nil, fmt.Errorf("invalid Privi bank genesis: %w", err)\\n'
        '\\t}\\n'
        f'\\tpreCap, validCap := sdkmath.NewIntFromString("{MAX_BASE}")\\n'
        '\\tif !validCap { return nil, fmt.Errorf("invalid Privi genesis cap") }\\n'
        '\\tinitialBalances := sdkmath.ZeroInt()\\n'
        '\\tfor _, entry := range bankGenesis.Balances {\\n'
        '\\t\\tinitialBalances = initialBalances.Add(entry.Coins.AmountOf("aprvi"))\\n'
        '\\t}\\n'
        '\\tif !bankGenesis.Supply.AmountOf("aprvi").Equal(preCap) || !initialBalances.Equal(preCap) {\\n'
        '\\t\\treturn nil, fmt.Errorf("Privi genesis native supply must equal exactly 1 billion PRVI")\\n'
        '\\t}\\n\\n'
        '\\tif err := app.UpgradeKeeper.SetModuleVersionMap(ctx, app.ModuleManager.GetVersionMap()); err != nil {',p)
    result[p]=x

    # Disables the *periodic minting path* in the example app (no inflation
    # even if mutable x/mint Genesis default inflation params are nonzero).
    # A production review MUST still audit all module mint authority pathways.
    p="evmd/app.go"
    x=result[p]
    x=checked_replace(x,'\t"errors"\n','\t"errors"\n\tsdkmath "cosmossdk.io/math"\n',p)
    # Cosmos SDK v0.54.3 requires each registered module to appear in the
    # BeginBlock ordering. DO NOT remove x/mint from SetOrderBeginBlockers:
    # doing so panics before the node can even run the 'init' command.
    # Instead embed the upstream x/mint module and override ONLY BeginBlock,
    # preserving genesis, services, migrations, codec and module ordering.
    x=checked_replace(x,'\t"encoding/json"\n','\t"context"\n\t"encoding/json"\n',p)
    x=checked_replace(x,
        'const appName = "evmd"',
        'type priviNoMintAppModule struct { mint.AppModule }\n'
        'func (priviNoMintAppModule) BeginBlock(_ context.Context) error { return nil }\n\n'
        'const appName = "evmd"',p)
    x=checked_replace(x,
        'mint.NewAppModule(appCodec, app.MintKeeper, app.AccountKeeper, nil, nil)',
        'priviNoMintAppModule{AppModule: mint.NewAppModule(appCodec, app.MintKeeper, app.AccountKeeper, nil, nil)}',p)
    # Patch the actual DefaultGenesis method: NewFeeMarketGenesisState
    # was defined upstream but never invoked, and x/staking otherwise
    # defaults to the SDK 'stake' denom instead of Privi's native aprvi.
    x=checked_replace(x,
        '\tgenesis[erc20types.ModuleName] = app.appCodec.MustMarshalJSON(erc20GenState)\n\n\treturn genesis',
        '\tgenesis[erc20types.ModuleName] = app.appCodec.MustMarshalJSON(erc20GenState)\n'
        '\tbankGenesis := banktypes.DefaultGenesisState()\n'
        '\tbankGenesis.DenomMetadata = []banktypes.Metadata{{\n'
        '\t\tDescription: "Privi native utility asset",\n'
        '\t\tDenomUnits: []*banktypes.DenomUnit{{Denom: "aprvi", Exponent: 0}, {Denom: "prvi", Exponent: 18}},\n'
        '\t\tBase: "aprvi", Display: "prvi", Name: "Privi", Symbol: "PRVI",\n'
        '\t}}\n'
        '\tgenesis[banktypes.ModuleName] = app.appCodec.MustMarshalJSON(bankGenesis)\n'
        '\tstakingGenesis := stakingtypes.DefaultGenesisState()\n'
        '\tstakingGenesis.Params.BondDenom = "aprvi"\n'
        '\tgenesis[stakingtypes.ModuleName] = app.appCodec.MustMarshalJSON(stakingGenesis)\n'
        '\tfeeGenesis := NewFeeMarketGenesisState()\n'
        '\tgenesis[feemarkettypes.ModuleName] = app.appCodec.MustMarshalJSON(feeGenesis)\n\n'
        '\treturn genesis',p)
    x=checked_replace(x,
        "func (app *EVMD) EndBlocker(ctx sdk.Context) (sdk.EndBlock, error) {\n"
        "\treturn app.ModuleManager.EndBlock(ctx)\n}",
        "func (app *EVMD) EndBlocker(ctx sdk.Context) (sdk.EndBlock, error) {\n"
        "\tresult, err := app.ModuleManager.EndBlock(ctx)\n"
        "\tif err != nil {\n\t\treturn result, err\n\t}\n"
        f'\tcap, ok := sdkmath.NewIntFromString("{MAX_BASE}")\n'
        '\tif !ok {\n\t\treturn result, fmt.Errorf("invalid Privi native supply cap")\n\t}\n'
        '\tif app.BankKeeper.GetSupply(ctx, "aprvi").Amount.GT(cap) {\n'
        '\t\treturn result, fmt.Errorf("PRVI supply above fixed maximum")\n\t}\n'
        '\treturn result, nil\n}',p)
    result[p]=x
    return result

def check_checkout(upstream):
    if not (upstream/"go.mod").is_file() or not (upstream/"evmd"/"go.mod").is_file():
        raise UnsafeInput("Not a complete upstream Cosmos EVM checkout")
    rev = subprocess.check_output(["git","-C",str(upstream),"rev-parse","HEAD"],text=True).strip()
    if rev != PIN:
        raise UnsafeInput(f"Upstream commit changed: {rev}")
    status=subprocess.check_output(["git","-C",str(upstream),"status","--porcelain"],text=True).strip()
    if status:
        raise UnsafeInput("Upstream checkout has uncommitted changes; use a CLEAN checkout")

def create_patch(upstream, chain_config):
    _, eid=validated_settings(chain_config)
    check_checkout(upstream)
    paths=["evmd/config/bech32.go","evmd/genesis.go","evmd/cmd/evmd/cmd/root.go","evmd/app.go"]
    old={p:(upstream/p).read_text(encoding="utf8") for p in paths}
    new=source_overlay(old,eid)
    segments=[]
    for path in paths:
        diff=list(difflib.unified_diff(old[path].splitlines(True),new[path].splitlines(True),
          fromfile="a/"+path,tofile="b/"+path))
        if not diff: raise UnsafeInput(f"Patch unexpectedly empty for {path}")
        segments.extend(["diff --git a/"+path+" b/"+path+"\n",*diff])
    return "".join(segments)

def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--upstream",required=True,type=Path,help="Clean pinned local cosmos/evm checkout; NEVER deployed state")
    a.add_argument("--config",type=Path,default=Path(__file__).with_name("privi_chain_config.json"))
    a.add_argument("--output",required=True,type=Path,help="New patch file only; file must not already exist")
    args=a.parse_args()
    if args.output.exists():
        raise UnsafeInput("Patch output already exists: refusing overwrite")
    data=json.loads(args.config.read_text(encoding="utf8"))
    patch=create_patch(args.upstream,data)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf8") as f:
        f.write(patch)
    print("Created UNREVIEWED source patch, SHA-256:",hashlib.sha256(patch.encode()).hexdigest())
    print("NOT a deployable binary, complete PRVI genesis, audit, or launch permission.")
    return 0

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (UnsafeInput, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print("BLOCKED:",exc,file=sys.stderr)
        raise SystemExit(1) from exc
