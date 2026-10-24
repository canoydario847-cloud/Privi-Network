// Package prvicap is a consensus-KV-backed PRVI genesis issuance guard
// intended for future integration into a reviewed custom Cosmos EVM app.
//
// STATUS: NOT WIRED INTO APP, NO REAL PRVI ISSUED.
// Policy: allocate <=1B PRVI at genesis; all later native PRVI mint operations
// MUST fail. This is stronger than a fractional new-issuance budget and makes
// burn-and-remint impossible through the guarded bank API.
//
// WARNING: This keeper alone is NOT sufficient. The app must mount its store,
// initialize it after bank genesis is reconciled, and apply MintRestriction to
// the SINGLE bank keeper passed to EVERY SDK/IBC/EVM module. Bypassable APIs
// (UncheckedSetBalance, app upgrades, genesis migrations) require auditing.
package prvicap

import (
    "context"
    "errors"
    "fmt"
    "math/big"

    corestore "cosmossdk.io/core/store"
    sdk "github.com/cosmos/cosmos-sdk/types"
    banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
)

const (
    BaseDenom = "aprvi" // Proposed denomination; requires final review
    Decimals = 18
    MaxWholePRVI = "1000000000"
    MaxBase = "1000000000000000000000000000"
)

var (
    ErrNotInitialized = errors.New("PRVI cap keeper not initialized")
    ErrAlreadyInitialized = errors.New("PRVI cap keeper already initialized")
    ErrInvalidGenesis = errors.New("invalid PRVI genesis supply")
    ErrBankSupplyMismatch = errors.New("genesis bank supply not equal to PRVI initial allocation")
    ErrMintForbidden = errors.New("native PRVI issuance forbidden after genesis")
    ErrStoreCorrupt = errors.New("PRVI cap consensus store is corrupt")
    ErrUnexpectedSupply = errors.New("PRVI bank supply exceeds genesis issuance or absolute cap")
)

var (
    keyGenesis = []byte{0x01} // immutable cumulative issuance; all new native mints disabled
    keyObservedSupply = []byte{0x02} // last validated outstanding native supply; must never rebound
)

// BankView has the pinned Cosmos SDK bank keeper's GetSupply signature.
// This interface lets the keeper reconcile bank supply without taking over
// module account access, staking, or normal bank sends.
type BankView interface {
    GetSupply(ctx context.Context, denom string) sdk.Coin
    // Check actual on-ledger account balances, not merely the bank Supply
    // metadata. UncheckedSetBalance can alter balances without changing
    // that metadata, bypassing a supply-only reconciliation.
    IterateAllBalances(ctx context.Context, cb func(address sdk.AccAddress, coin sdk.Coin) (stop bool))
}

type State struct {
    GenesisBase string `json:"genesis_base"`
    LifetimeIssuedBase string `json:"lifetime_issued_base"`
    MaximumBase string `json:"maximum_base"`
    MintPolicy string `json:"mint_policy"`
}

type Keeper struct {
    store corestore.KVStoreService
}

func New(store corestore.KVStoreService) (Keeper, error) {
    if store == nil { return Keeper{}, errors.New("nil PRVI consensus KVStoreService") }
    return Keeper{store: store}, nil
}

func parseCanonical(raw string) (*big.Int,error) {
    if len(raw)==0 || raw[0]=='0' { return nil,ErrInvalidGenesis }
    for _,char:=range []byte(raw) {
        if char<'0'||char>'9' { return nil,ErrInvalidGenesis }
    }
    value,ok:=new(big.Int).SetString(raw,10)
    if !ok||value.Sign()<=0 {return nil,ErrInvalidGenesis}
    return value,nil
}

func capValue() *big.Int {
    value,ok:=new(big.Int).SetString(MaxBase,10)
    if !ok { panic("invalid embedded maximum PRVI supply") }
    return value
}

// ValidateGenesisBase is a *pure* preflight: no KV reads, writes, mint,
// or transaction effects. Call it before ANY app module InitGenesis work
// to reject empty/default demo genesis and oversupply without partially
// initializing modules. InitGenesis independently repeats this validation
// before persisting the consensus cap to defend against inconsistent callers.
func ValidateGenesisBase(genesisBase string) error {
    value,err:=parseCanonical(genesisBase)
    if err!=nil || value.Cmp(capValue())>0 {return ErrInvalidGenesis}
    return nil
}


func (k Keeper) kv(ctx context.Context) (corestore.KVStore,error) {
    if k.store == nil { return nil,errors.New("unconfigured cap keeper") }
    if ctx == nil {return nil,errors.New("nil block context")}
    return k.store.OpenKVStore(ctx),nil
}

// InitGenesis MUST be called exactly once within app InitGenesis, AFTER bank
// genesis is loaded. Requires the actual already-reconciled bank.GetSupply
// to equal the independently approved allocation. No self-chosen coins minted.
func (k Keeper) InitGenesis(ctx context.Context, genesisBase string, bank BankView) error {
    if bank==nil {return ErrBankSupplyMismatch}
    value,err:=parseCanonical(genesisBase)
    if err!=nil||value.Cmp(capValue())>0 {return ErrInvalidGenesis}
    kv,err:=k.kv(ctx)
    if err!=nil {return err}
    got,err:=kv.Get(keyGenesis)
    if err!=nil {return err}
    if got!=nil {return ErrAlreadyInitialized}
    // A missing genesis record with an existing observation indicates
    // interrupted/corrupt initialization. Never overwrite issuance history.
    observed,err:=kv.Get(keyObservedSupply)
    if err!=nil {return err}
    if observed!=nil {return ErrStoreCorrupt}
    bankCoins:=bank.GetSupply(ctx,BaseDenom)
    if bankCoins.Denom!=BaseDenom || !bankCoins.Amount.IsPositive() ||
       bankCoins.Amount.String()!=value.String() {return ErrBankSupplyMismatch}
    // A declared supply is insufficient: unchecked native balance setters
    // can change real account balances without updating x/bank Supply.
    // Reject such a genesis BEFORE writing the immutable cap record.
    if err:=checkNativeBalances(ctx,bank,value);err!=nil {
        return fmt.Errorf("%w: %v",ErrBankSupplyMismatch,err)
    }
    // Seed the observed outstanding supply at genesis. A later missing
    // observation must fail closed: otherwise deleting that key after a burn
    // would silently restore the original issuance ceiling.
    // These two writes MUST occur in an uncommitted SDK cache context; any
    // error must abort/rollback the entire app InitChain, not commit a partial
    // genesis record. Full SDK rollback proof is still a launch blocker.
    if err:=kv.Set(keyObservedSupply,[]byte(value.String()));err!=nil {return err}
    return kv.Set(keyGenesis,[]byte(value.String()))
}

func (k Keeper) read(ctx context.Context) (*big.Int,*big.Int,error) {
    kv,err:=k.kv(ctx)
    if err!=nil {return nil,nil,err}
    rawGenesis,err:=kv.Get(keyGenesis)
    if err!=nil {return nil,nil,err}
    if rawGenesis==nil {return nil,nil,ErrNotInitialized}
    genesis,err:=parseCanonical(string(rawGenesis))
    if err!=nil || genesis.Cmp(capValue())>0 {return nil,nil,ErrStoreCorrupt}
    // The burn watermark is part of the required consensus state, not
    // optional reporting metadata. A missing/corrupt observation must not
    // produce a healthy snapshot or mint-policy result.
    rawObserved,err:=kv.Get(keyObservedSupply)
    if err!=nil {return nil,nil,err}
    if rawObserved==nil {return nil,nil,ErrStoreCorrupt}
    observed,ok:=new(big.Int).SetString(string(rawObserved),10)
    if !ok || observed.Sign()<0 || observed.Cmp(genesis)>0 ||
       observed.String()!=string(rawObserved) {return nil,nil,ErrStoreCorrupt}
    // All native PRVI minting is prohibited after genesis. Lifetime issued
    // remains exactly the genesis amount even when outstanding supply burns.
    return genesis,new(big.Int).Set(genesis),nil
}

// Snapshot reads only consensus-backed state. Every new SDK context targeting
// the same mounted store sees the same immutable issuance history.
func (k Keeper) Snapshot(ctx context.Context) (State,error) {
    genesis,lifetime,err:=k.read(ctx)
    if err!=nil {return State{},err}
    return State{
        GenesisBase:genesis.String(),LifetimeIssuedBase:lifetime.String(),
        MaximumBase:MaxBase,MintPolicy:"NO_NEW_NATIVE_PRVI_MINTS",
    },nil
}

// MintRestriction has precisely the Cosmos SDK v0.54.3 banktypes.MintingRestrictionFn
// signature used by BaseKeeper.WithMintCoinsRestriction. It checks keeper
// initialization FIRST to avoid accepting any mint during broken migrations.
// It blocks PRVI natively, including attempts via x/mint, ERC20, IBC and VM,
// *provided every module's bank keeper uses the same restricted bank instance*.
// Other denominations are unaffected by this specific asset guard.
func (k Keeper) MintRestriction(ctx context.Context, coins sdk.Coins) error {
    // Before and after InitGenesis, deny every native PRVI mint.
    // Allow ONLY unrelated denominations to follow ordinary SDK rules,
    // including during modules' genesis initialization. SDK's underlying
    // account/mint permission checks still apply to these unrelated coins.
    // This never permits PRVI minting when its cap store is unavailable.
    hasNative := false
    for _,coin:=range coins {
        if coin.Denom==BaseDenom {hasNative=true;break}
    }
    if !hasNative {return nil}
    if _,_,err:=k.read(ctx);err!=nil {return err}
    return ErrMintForbidden
}

// Reconcile rejects native supply above the immutable genesis allocation AND
// any increase after a previously observed burn. Burns never restore mint budget.
// An end-of-block scan detects untracked net balance changes but NOT
// unauthorized mint+burn that cancels out inside one block. This O(accounts)
// check is provisional; it requires scale benchmarks and alternative
// issuance hooks before final financial deployment.
func (k Keeper) Reconcile(ctx context.Context, bank BankView) error {
    if bank==nil {return ErrUnexpectedSupply}
    _,lifetime,err:=k.read(ctx)
    if err!=nil {return err}
    supply:=bank.GetSupply(ctx,BaseDenom)
    if supply.Denom!=BaseDenom || supply.Amount.IsNegative() {
        return fmt.Errorf("%w: invalid denom/amount",ErrUnexpectedSupply)
    }
    if supply.Amount.BigInt().Cmp(lifetime)>0 || supply.Amount.BigInt().Cmp(capValue())>0 {
        return ErrUnexpectedSupply
    }
    // Track the last successfully validated outstanding supply in consensus KV.
    // Without this, a burn in block N followed by a smaller unauthorized mint
    // in block N+1 could stay below genesis and evade the absolute cap check.
    kv,err:=k.kv(ctx)
    if err!=nil {return err}
    raw,err:=kv.Get(keyObservedSupply)
    if err!=nil {return err}
    if raw==nil {return ErrStoreCorrupt}
    last,ok:=new(big.Int).SetString(string(raw),10)
    if !ok || last.Sign()<0 || last.Cmp(lifetime)>0 || last.String()!=string(raw) {
        return ErrStoreCorrupt
    }
    current:=supply.Amount.BigInt()
    if current.Cmp(last)>0 {return ErrUnexpectedSupply}
    // Validate account conservation before persisting any new observation.
    if err:=checkNativeBalances(ctx,bank,current);err!=nil {return err}
    if current.Cmp(last)<0 {
        return kv.Set(keyObservedSupply,[]byte(current.String()))
    }
    return nil
}

// checkNativeBalances is shared by genesis preflight and block boundaries.
// Checking the *actual* account sum prevents an unchecked balance mutation
// from hiding behind unchanged x/bank supply metadata. O(number of accounts)
// per call; this must be replaced or optimized before financial production.
func checkNativeBalances(ctx context.Context,bank BankView,declared *big.Int) error {
    actual:=new(big.Int)
    invalid:=false
    bank.IterateAllBalances(ctx,func(_ sdk.AccAddress,coin sdk.Coin) bool {
        if coin.Denom!=BaseDenom {return false}
        if coin.Amount.IsNegative() {invalid=true;return true}
        actual.Add(actual,coin.Amount.BigInt())
        if actual.Cmp(declared)>0 {invalid=true;return true}
        return false
    })
    if invalid || actual.Cmp(declared)!=0 {
        return fmt.Errorf("%w: native bank supply/balances mismatch",ErrUnexpectedSupply)
    }
    return nil
}

var _ banktypes.MintingRestrictionFn = (Keeper{}).MintRestriction
