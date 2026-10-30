package prvicap

import (
  "context"
  "errors"
  "math/big"
  "strings"
  "testing"

  corestore "cosmossdk.io/core/store"
  sdkmath "cosmossdk.io/math"
  sdk "github.com/cosmos/cosmos-sdk/types"
)

type fakeKV struct {
  content map[string][]byte
  readErr error
  writeErr error
}
func newFakeKV() *fakeKV {return &fakeKV{content:map[string][]byte{}}}
func (m *fakeKV) Get(key []byte) ([]byte,error) {
  if m.readErr!=nil {return nil,m.readErr}
  if v,ok:=m.content[string(key)];ok{return append([]byte{},v...),nil}
  return nil,nil
}
func (m *fakeKV) Has(key []byte) (bool,error) {
  v,err:=m.Get(key);return v!=nil,err
}
func (m *fakeKV) Set(key,value []byte) error {
  if m.writeErr!=nil {return m.writeErr}
  m.content[string(key)]=append([]byte{},value...);return nil
}
func (m *fakeKV) Delete(key []byte) error {delete(m.content,string(key));return nil}
func (*fakeKV) Iterator([]byte,[]byte) (corestore.Iterator,error) {return nil,errors.New("not implemented for point lookup tests")}
func (*fakeKV) ReverseIterator([]byte,[]byte) (corestore.Iterator,error) {return nil,errors.New("not implemented for point lookup tests")}

type fakeService struct {data *fakeKV}
func (s fakeService) OpenKVStore(context.Context) corestore.KVStore {return s.data}
type fakeBank struct {
  base sdkmath.Int
  actual *sdkmath.Int // absent = matches declared supply for existing cases
}
func (b fakeBank) GetSupply(_ context.Context, denom string) sdk.Coin {
  return sdk.NewCoin(denom,b.base)
}
func (b fakeBank) IterateAllBalances(_ context.Context, cb func(sdk.AccAddress,sdk.Coin)bool) {
  amount:=b.base
  if b.actual!=nil {amount=*b.actual}
  if amount.IsPositive() {cb(sdk.AccAddress(make([]byte,20)),sdk.NewCoin(BaseDenom,amount))}
}
func coins(prvi sdkmath.Int) sdk.Coins {return sdk.NewCoins(sdk.NewCoin(BaseDenom,prvi))}
func whole(n int64) string {
  return new(big.Int).Mul(big.NewInt(n),big.NewInt(1_000_000_000_000_000_000)).String()
}
func setup(t *testing.T, genesis string) (Keeper,*fakeKV,context.Context) {
  t.Helper()
  data:=newFakeKV()
  keeper,err:=New(fakeService{data})
  if err!=nil {t.Fatal(err)}
  ctx:=context.Background()
  amount,ok:=new(big.Int).SetString(genesis,10)
  if !ok {t.Fatal("invalid test value")}
  if err:=keeper.InitGenesis(ctx,genesis,fakeBank{base:sdkmath.NewIntFromBigInt(amount)});err!=nil{t.Fatal(err)}
  return keeper,data,ctx
}
func TestInitEmptyStoreFailClosed(t *testing.T) {
  data:=newFakeKV()
  k,_:=New(fakeService{data})
  ctx:=context.Background()
  if _,err:=k.Snapshot(ctx);!errors.Is(err,ErrNotInitialized){t.Fatal(err)}
  if err:=k.MintRestriction(ctx,coins(sdkmath.NewInt(1)));!errors.Is(err,ErrNotInitialized){t.Fatal(err)}
  if err:=k.MintRestriction(ctx,sdk.NewCoins(sdk.NewInt64Coin("other",1)));err!=nil{t.Fatalf("unrelated genesis denom should follow normal SDK mint checks: %v",err)}
}
func TestGenesisAndPersistAcrossKeeperReopen(t *testing.T) {
  initial:=whole(750_000_000)
  k,data,ctx:=setup(t,initial)
  state,err:=k.Snapshot(ctx)
  if err!=nil {t.Fatal(err)}
  if state.GenesisBase!=initial||state.LifetimeIssuedBase!=initial||state.MaximumBase!=MaxBase {t.Fatalf("%+v",state)}
  // Simulates constructing a brand-new keeper using the same mounted
  // consensus store; in production persistence is delivered by SDK runtime.
  restarted,err:=New(fakeService{data})
  if err!=nil {t.Fatal(err)}
  result,err:=restarted.Snapshot(context.WithValue(ctx, struct{}{}, 1))
  if err!=nil || result!=state {t.Fatalf("reopen failed: %+v, %v",result,err)}
}
func TestAllNewNativePrviMintingProhibited(t *testing.T){
  k,data,ctx:=setup(t,whole(1_000_000_000))
  before:=string(data.content[string(keyGenesis)])
  for _,amount:=range []int64{1,5,50_000_000} {
    if err:=k.MintRestriction(ctx,coins(sdkmath.NewInt(amount)));!errors.Is(err,ErrMintForbidden) {
      t.Fatalf("should forbid native mint, %d: %v",amount,err)
    }
  }
  if err:=k.MintRestriction(ctx,sdk.NewCoins(
    sdk.NewInt64Coin("other",1),sdk.NewInt64Coin(BaseDenom,1)));!errors.Is(err,ErrMintForbidden) {
    t.Fatal("cannot permit mixed native+other mint",err)
  }
  if err:=k.MintRestriction(ctx,sdk.NewCoins(sdk.NewInt64Coin("other",100)));err!=nil {t.Fatal(err)}
  if string(data.content[string(keyGenesis)])!=before {t.Fatal("mint restriction mutated persisted lifetime")}
}
func TestBurnDoesNotUnlockNewMint(t *testing.T) {
  k,_,ctx:=setup(t,MaxBase)
  if err:=k.Reconcile(ctx,fakeBank{base:sdkmath.NewIntFromBigInt(big.NewInt(100))});err!=nil {
    t.Fatal("burned supply below cap should remain valid",err)
  }
  if err:=k.MintRestriction(ctx,coins(sdkmath.NewInt(1)));!errors.Is(err,ErrMintForbidden){
    t.Fatal("burn must not permit remint",err)
  }
  state,_:=k.Snapshot(ctx)
  if state.LifetimeIssuedBase!=MaxBase {t.Fatal("burn reset cumulative issued")}
}
func TestGenesisMismatchesFailWithoutStoreMutation(t *testing.T) {
  values:=[]string{"0","-1","+1","", "01","1.0", "1e18",whole(1_000_000_000)+"1"}
  for _,value:=range values {
    data:=newFakeKV()
    k,_:=New(fakeService{data})
    err:=k.InitGenesis(context.Background(),value,fakeBank{base:sdkmath.NewInt(1)})
    if !errors.Is(err,ErrInvalidGenesis) {t.Fatalf("%q: %v",value,err)}
    if len(data.content)!=0 {t.Fatal("invalid genesis wrote consensus state")}
  }
  data:=newFakeKV()
  k,_:=New(fakeService{data})
  err:=k.InitGenesis(context.Background(),whole(5),fakeBank{base:sdkmath.NewInt(4)})
  if !errors.Is(err,ErrBankSupplyMismatch){t.Fatal(err)}
  if len(data.content)!=0{t.Fatal("bank mismatch wrote state")}
}
func TestRepeatedGenesisInitializationFails(t *testing.T) {
  k,data,ctx:=setup(t,whole(100))
  before:=string(data.content[string(keyGenesis)])
  if err:=k.InitGenesis(ctx,whole(10),fakeBank{base:sdkmath.NewIntFromBigInt(big.NewInt(10))});!errors.Is(err,ErrAlreadyInitialized){t.Fatal(err)}
  if got:=string(data.content[string(keyGenesis)]);got!=before {t.Fatal("reset counter")}
}
func TestReconcileDetectsOverIssuance(t *testing.T){
  k,_,ctx:=setup(t,whole(700))
  amount,_:=new(big.Int).SetString(whole(700),10)
  amount.Add(amount,big.NewInt(1))
  if err:=k.Reconcile(ctx,fakeBank{base:sdkmath.NewIntFromBigInt(amount)});!errors.Is(err,ErrUnexpectedSupply){t.Fatal(err)}
  if err:=k.Reconcile(ctx,fakeBank{base:sdkmath.NewIntFromBigInt(big.NewInt(1))});err!=nil {t.Fatal(err)}
}
func TestStorageCorruptionAlwaysFailsClosed(t *testing.T){
  k,data,ctx:=setup(t,whole(1))
  for _,bad:=range []string{"","0","-1","001","xyz","1000000000000000000000000001"} {
    data.content[string(keyGenesis)]=[]byte(bad)
    if _,err:=k.Snapshot(ctx);!errors.Is(err,ErrStoreCorrupt){t.Fatalf("%q: %v",bad,err)}
    if err:=k.MintRestriction(ctx,coins(sdkmath.NewInt(1)));!errors.Is(err,ErrStoreCorrupt){t.Fatal(err)}
  }
}
func TestStoreFailuresFailClosed(t *testing.T){
  data:=newFakeKV()
  k,_:=New(fakeService{data})
  ctx:=context.Background()
  data.readErr=errors.New("read unavailable")
  if err:=k.MintRestriction(ctx,coins(sdkmath.NewInt(1)));err==nil {t.Fatal("store read error ignored")}
  data.readErr=nil
  data.writeErr=errors.New("disk failure")
  if err:=k.InitGenesis(ctx,whole(1),fakeBank{base:sdkmath.NewInt(1_000_000_000_000_000_000)});err==nil {t.Fatal("ignored disk failure")}
  if len(data.content)!=0 {t.Fatal("failed store write mutated state")}
}
func TestRejectNilStoreOrBank(t *testing.T) {
  if _,err:=New(nil);err==nil {t.Fatal("nil store accepted")}
  k,_:=New(fakeService{newFakeKV()})
  if err:=k.InitGenesis(context.Background(),whole(1),nil);!errors.Is(err,ErrBankSupplyMismatch){t.Fatal(err)}
  if err:=k.Reconcile(context.Background(),nil);!errors.Is(err,ErrUnexpectedSupply){t.Fatal(err)}
}

func TestPureGenesisDeclarationPreflightRejectsInvalidOrAboveCap(t *testing.T) {
    for _,good:=range []string{"1",whole(1),whole(750_000_000),MaxBase} {
        if err:=ValidateGenesisBase(good);err!=nil {
            t.Fatalf("accepted-range declaration %q denied: %v",good,err)
        }
    }
    capPlusOne,ok:=new(big.Int).SetString(MaxBase,10)
    if !ok {t.Fatal("invalid max PRVI constant")}
    capPlusOne.Add(capPlusOne,big.NewInt(1))
    for _,bad:=range []string{"","0","00","01","-1","+1"," 1","1 ","1.0",
        "1e18",capPlusOne.String(),"1234567890123456789012345678901234567890"} {
        if err:=ValidateGenesisBase(bad);!errors.Is(err,ErrInvalidGenesis) {
            t.Fatalf("bad declaration %q not rejected fail-closed: %v",bad,err)
        }
    }
}


func TestReconcileRejectsUntrackedDirectBalanceMutations(t *testing.T) {
  initial:=sdkmath.NewInt(1000)
  k,_,ctx:=setup(t,initial.String())
  above:=sdkmath.NewInt(1001)
  below:=sdkmath.NewInt(999)
  // These simulate the real SDK's dangerous UncheckedSetBalance, which
  // changes account records WITHOUT automatically updating x/bank supply.
  // The declared supply still looks capped, but real balances diverge.
  for _,actual:=range []sdkmath.Int{above,below} {
    err:=k.Reconcile(ctx,fakeBank{base:initial,actual:&actual})
    if !errors.Is(err,ErrUnexpectedSupply) {
      t.Fatalf("untracked native balance edit (%s) went undetected: %v",actual,err)
    }
  }
  if err:=k.Reconcile(ctx,fakeBank{base:initial});err!=nil {
    t.Fatalf("normal native supply conservation was falsely rejected: %v",err)
  }
}

// TestOversizedGenesisAndCorruptStoreFailClosed prevents unbounded big.Int
// parsing of untrusted genesis strings or corrupt persisted issuance data.
func TestOversizedGenesisAndCorruptStoreFailClosed(t *testing.T) {
  oversized := strings.Repeat("9", 100_000)
  if err:=ValidateGenesisBase(oversized);!errors.Is(err,ErrInvalidGenesis) {
    t.Fatalf("oversized genesis preflight was not rejected: %v",err)
  }
  data:=newFakeKV()
  k,_:=New(fakeService{data})
  if err:=k.InitGenesis(context.Background(),oversized,fakeBank{base:sdkmath.NewInt(1)});!errors.Is(err,ErrInvalidGenesis) {
    t.Fatalf("oversized genesis init was not rejected: %v",err)
  }
  if len(data.content)!=0 {t.Fatal("rejected oversized genesis wrote consensus state")}

  initialized,store,ctx:=setup(t,whole(1))
  store.content[string(keyGenesis)]=[]byte(oversized)
  if _,err:=initialized.Snapshot(ctx);!errors.Is(err,ErrStoreCorrupt) {
    t.Fatalf("oversized persisted issuance was not rejected: %v",err)
  }
  if err:=initialized.MintRestriction(ctx,coins(sdkmath.NewInt(1)));!errors.Is(err,ErrStoreCorrupt) {
    t.Fatalf("oversized persisted issuance did not block native mint: %v",err)
  }
}
