package mintscan

import (
  "os"
  "path/filepath"
  "strings"
  "testing"
)

const examplePermissions = `package config
var maccPerms=map[string][]string{
  transfertypes.ModuleName: {authtypes.Minter, authtypes.Burner},
  minttypes.ModuleName: {authtypes.Minter},
  vmtypes.ModuleName: {authtypes.Minter, authtypes.Burner},
  erc20types.ModuleName: {authtypes.Minter, authtypes.Burner},
  govtypes.ModuleName: {authtypes.Burner},
}
`
const exampleApp = `package evmd
func configure() {
  bankkeeper.NewBaseKeeper()
  mintkeeper.NewKeeper()
  mint.NewAppModule()
}
`
const exampleERC = `package keeper
func convert() {k.bankKeeper.MintCoins(ctx, "erc20", coins)}
`
const exampleGenesis = `package evmd
func setup() { minttypes.DefaultGenesisState() }
`

func write(t *testing.T, root,path, content string) {
  t.Helper()
  dest:=filepath.Join(root,path)
  if err:=os.MkdirAll(filepath.Dir(dest),0755);err!=nil {t.Fatal(err)}
  if err:=os.WriteFile(dest,[]byte(content),0644);err!=nil {t.Fatal(err)}
}
func fixture(t *testing.T) string {
  t.Helper()
  dir:=t.TempDir()
  write(t,dir,"evmd/app.go",exampleApp)
  write(t,dir,"evmd/genesis.go",exampleGenesis)
  write(t,dir,"evmd/config/permissions.go",examplePermissions)
  write(t,dir,"x/erc20/keeper/convert.go",exampleERC)
  return dir
}
func TestExpectedPinnedRoutesPassButLaunchRemainsBlocked(t *testing.T){
  root:=fixture(t)
  r,err:=Scan(root)
  if err!=nil {t.Fatal(err)}
  if len(r.FoundCalls)!=5 || len(r.MintPermissionModules)!=4 {t.Fatalf("%+v",r)}
  if r.LaunchVerdict!="NO_GO" || r.ProductionEnforcement!="NOT_IMPLEMENTED" ||
     !strings.Contains(r.SourceInventory,"UNSAFE_TO_DEPLOY") {
    t.Fatalf("inventory must never declare financial mainnet GO: %+v",r)
  }
}
func TestNewMintCallsiteFailsClosed(t *testing.T){
  root:=fixture(t)
  write(t,root,"x/vm/keeper/new_mint.go","package keeper
func mint(){ k.bankKeeper.MintCoins(ctx, "mint", coins) }
")
  r,err:=Scan(root)
  if err==nil {t.Fatal("unexpected MintCoins route must be reviewed")}
  if len(r.FoundCalls)!=6 {t.Fatalf("expected added mint path, got %+v",r.FoundCalls)}
}
func TestMissingERC20MintCallsiteFailsClosed(t *testing.T){
  root:=fixture(t)
  write(t,root,"x/erc20/keeper/convert.go","package keeper
func convert(){}
")
  if _,err:=Scan(root);err==nil {t.Fatal("missing mint site needs source review")}
}
func TestUnexpectedMinterModuleFailsClosed(t *testing.T){
  root:=fixture(t)
  write(t,root,"evmd/config/permissions.go",strings.Replace(examplePermissions,
    "govtypes.ModuleName: {authtypes.Burner}",
    "govtypes.ModuleName: {authtypes.Minter, authtypes.Burner}",1))
  if _,err:=Scan(root);err==nil {t.Fatal("new authorized minter must block readiness")}
}
func TestMissingMinterPrivilegeFailsClosed(t *testing.T){
  root:=fixture(t)
  write(t,root,"evmd/config/permissions.go",strings.Replace(examplePermissions,
    "minttypes.ModuleName: {authtypes.Minter}","minttypes.ModuleName: nil",1))
  if _,err:=Scan(root);err==nil {t.Fatal("upstream privilege drift needs review")}
}
func TestParseSyntaxErrorFailsClosed(t *testing.T) {
  root:=fixture(t)
  write(t,root,"evmd/app.go","package evmd
func broken( {
")
  if _,err:=Scan(root);err==nil {t.Fatal("unparseable source must reject")}
}
func TestIgnoresTestOnlyMinting(t *testing.T){
  root:=fixture(t)
  write(t,root,"x/erc20/keeper/convert_test.go","package keeper
func fake(){k.bankKeeper.MintCoins(ctx,"mint",coins)}
")
  write(t,root,"evmd/tests/integration/foo.go","package tests
func fake(){k.bankKeeper.MintCoins(ctx,"mint",coins)}
")
  if _,err:=Scan(root);err!=nil {t.Fatal(err)}
}
func TestMissingSourceAndPermissionsFailsClosed(t *testing.T){
  root:=t.TempDir()
  if _,err:=Scan(root);err==nil {t.Fatal("empty source must block readiness")}
}
