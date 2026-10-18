// Package mintscan inventories selected native-coin minting entry points in
// pinned Cosmos EVM application source. This is an OFF-CHAIN source audit,
// NOT runtime enforcement of the PRVI supply cap.
package mintscan

import (
  "errors"
  "fmt"
  "go/ast"
  "go/parser"
  "go/token"
  "io/fs"
  "path/filepath"
  "sort"
  "strings"
)

const UpstreamTag = "v0.7.3"

type Finding struct {
  Path string `json:"path"`
  Call string `json:"call"`
}

type Report struct {
  UpstreamTag string `json:"pinned_upstream_tag"`
  SourceInventory string `json:"source_inventory_status"`
  FoundCalls []Finding `json:"critical_call_sites"`
  MintPermissionModules []string `json:"modules_with_minter_permission"`
  ProductionEnforcement string `json:"production_cap_enforcement"`
  LaunchVerdict string `json:"financial_mainnet_verdict"`
  MissingIntegration []string `json:"still_required"`
}

// Expected v0.7.3 application wiring and Cosmos EVM-owned direct mint calls.
// All entries are deliberately reviewed literal source baselines, not wildcards.
var expectedCalls = []Finding{
  {"evmd/app.go", "bankkeeper.NewBaseKeeper"},
  {"evmd/app.go", "mint.NewAppModule"},
  {"evmd/app.go", "mintkeeper.NewKeeper"},
  {"evmd/genesis.go", "minttypes.DefaultGenesisState"},
  {"x/erc20/keeper/convert.go", "k.bankKeeper.MintCoins"},
}

// Account mint privileges from v0.7.3 evmd/config/permissions.go.
// Critically, x/mint, IBC transfer, EVM and ERC-20 have minter privileges;
// routes within Cosmos SDK / IBC dependencies are OUTSIDE this scanner.
var expectedMinterModules = []string{
  "erc20types.ModuleName",
  "minttypes.ModuleName",
  "transfertypes.ModuleName",
  "vmtypes.ModuleName",
}

var sentinel = errors.New("pinned Cosmos EVM native issuance paths changed; security review required")

func expressionName(expr ast.Expr) string {
  switch v := expr.(type) {
  case *ast.Ident:
    return v.Name
  case *ast.SelectorExpr:
    base := expressionName(v.X)
    if base != "" { return base+"."+v.Sel.Name }
    return v.Sel.Name
  }
  return ""
}

func importantCall(name string) bool {
  if name == "bankkeeper.NewBaseKeeper" ||
    name == "mintkeeper.NewKeeper" ||
    name == "mint.NewAppModule" ||
    name == "minttypes.DefaultGenesisState" { return true }
  // All direct bank mint calls in our scan scope, regardless of receiver.
  return strings.HasSuffix(name, ".MintCoins") || name == "MintCoins"
}

func permissionModules(file *ast.File) ([]string, error) {
  matches:=0
  modules:=make([]string,0)
  for _,decl:=range file.Decls {
    g,ok:=decl.(*ast.GenDecl)
    if !ok || g.Tok != token.VAR {continue}
    for _,spec:=range g.Specs {
      v,ok:=spec.(*ast.ValueSpec)
      if !ok {continue}
      for i,name:=range v.Names {
        if name.Name!="maccPerms" {continue}
        matches++
        if i>=len(v.Values) {return nil,fmt.Errorf("maccPerms is not initialized")}
        literal,ok:=v.Values[i].(*ast.CompositeLit)
        if !ok {return nil,fmt.Errorf("maccPerms is not a literal")}
        for _,row:=range literal.Elts {
          pair,ok:=row.(*ast.KeyValueExpr)
          if !ok {return nil,fmt.Errorf("unrecognized maccPerms mapping")}
          key:=expressionName(pair.Key)
          if key=="" {return nil,fmt.Errorf("dynamic minter permission key")}
          if ident,ok:=pair.Value.(*ast.Ident);ok && ident.Name=="nil" {continue}
          val,ok:=pair.Value.(*ast.CompositeLit)
          if !ok {return nil,fmt.Errorf("unreviewed permissions for %s",key)}
          for _,elem:=range val.Elts {
            role:=expressionName(elem)
            if role=="" {return nil,fmt.Errorf("dynamic role for %s",key)}
            if role=="authtypes.Minter" {
              modules=append(modules,key)
            }
          }
        }
      }
    }
  }
  if matches!=1 {return nil,fmt.Errorf("expected exactly one static maccPerms map, found %d",matches)}
  sort.Strings(modules)
  return modules,nil
}

func excludedDirectory(name string) bool {
  switch name {
  case ".git", ".testnets", "vendor", "node_modules",
    "testdata", "testutil", "tests", "mock", "mocks", "simulation", "simulations":
    return true
  }
  return false
}

// Scan checks production Go sources owned by the pinned cosmos/evm upstream
// in directories evmd/ and x/. It does NOT recursively inspect Cosmos SDK,
// IBC, precompiled EVM dependencies, dynamically selected bank routes or code
// outside these folders. Never claim source scan alone proves financial safety.
func Scan(root string) (Report,error) {
  report:=Report{
    UpstreamTag:UpstreamTag,
    SourceInventory:"NOT_VERIFIED",
    ProductionEnforcement:"NOT_IMPLEMENTED",
    LaunchVerdict:"NO_GO",
    MissingIntegration:[]string{
      "Custom PRVI Cosmos SDK consensus keeper and deterministic persistent lifetime counter",
      "Audit and atomically guard all Cosmos SDK / IBC mint routes, modules and bank authorities",
      "Disable or comprehensively cap native-denom x/mint inflation and ERC-20/IBC conversion",
      "Reconcile genesis, module balances, staking, fees, burns and upgrades",
      "Four independently operated validators, public testnet, security audit and approvals",
    },
    FoundCalls:[]Finding{},
    MintPermissionModules:[]string{},
  }
  rootAbs,err:=filepath.Abs(root)
  if err!=nil {return report,err}
  var seenPermissions bool
  var totalGo int
  for _,prefix:=range []string{"evmd","x"} {
    path:=filepath.Join(rootAbs,prefix)
    if err:=filepath.WalkDir(path,func(full string,entry fs.DirEntry,visitErr error) error {
      if visitErr!=nil {return visitErr}
      if entry.IsDir() {
        if full!=path && excludedDirectory(entry.Name()) {return filepath.SkipDir}
        return nil
      }
      if !strings.HasSuffix(entry.Name(),".go") || strings.HasSuffix(entry.Name(),"_test.go") {return nil}
      rel,err:=filepath.Rel(rootAbs,full)
      if err!=nil {return err}
      rel=filepath.ToSlash(rel)
      fset:=token.NewFileSet()
      node,err:=parser.ParseFile(fset,full,nil,parser.AllErrors)
      if err!=nil {return fmt.Errorf("%s: %w",rel,err)}
      totalGo++
      ast.Inspect(node,func(n ast.Node) bool {
        call,ok:=n.(*ast.CallExpr)
        if !ok {return true}
        name:=expressionName(call.Fun)
        if importantCall(name) {
          report.FoundCalls=append(report.FoundCalls,Finding{rel,name})
        }
        return true
      })
      if rel=="evmd/config/permissions.go" {
        if seenPermissions{return errors.New("duplicate permission source")}
        seenPermissions=true
        perms,err:=permissionModules(node)
        if err!=nil {return err}
        report.MintPermissionModules=perms
      }
      return nil
    });err!=nil {return report,err}
  }
  if totalGo<3 || !seenPermissions {return report,fmt.Errorf("%w: upstream source or permissions missing",sentinel)}
  sort.Slice(report.FoundCalls,func(i,j int)bool{
    if report.FoundCalls[i].Path==report.FoundCalls[j].Path {
      return report.FoundCalls[i].Call<report.FoundCalls[j].Call
    }
    return report.FoundCalls[i].Path<report.FoundCalls[j].Path
  })
  if len(report.FoundCalls)!=len(expectedCalls) {
    return report,fmt.Errorf("%w: %d direct sites, expected %d: %v",sentinel,len(report.FoundCalls),len(expectedCalls),report.FoundCalls)
  }
  for i,item:=range expectedCalls {
    if report.FoundCalls[i]!=item {return report,fmt.Errorf("%w: direct call drift at index %d: %+v",sentinel,i,report.FoundCalls[i])}
  }
  if len(report.MintPermissionModules)!=len(expectedMinterModules) {
    return report,fmt.Errorf("%w: %d minter module accounts, expected %d: %v",
      sentinel,len(report.MintPermissionModules),len(expectedMinterModules),report.MintPermissionModules)
  }
  for i,item:=range expectedMinterModules {
    if report.MintPermissionModules[i]!=item {
      return report,fmt.Errorf("%w: minter permission drift at index %d: %s",sentinel,i,report.MintPermissionModules[i])
    }
  }
  report.SourceInventory="PINNED_ROUTES_ACCOUNTED_FOR__UNSAFE_TO_DEPLOY"
  return report,nil
}
