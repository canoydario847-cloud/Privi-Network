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
    keyGenesis = []byte{0x01}
    keyLifetime = []byte{0x02}
)

// BankView has the pinned Cosmos SDK bank keeper's GetSupply signature.
// This interface lets the keeper reconcile bank supply without taking over
// module account access, staking, or normal bank sends.
type BankView interface {
    GetSupply(ctx context.Context, denom string) sdk.Coin
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
    lifetime,err:=kv.Get(keyLifetime)
    if err!=nil {return err}
    if lifetime!=nil {return ErrStoreCorrupt}
    bankCoins:=bank.GetSupply(ctx,BaseDenom)
    if bankCoins.Denom!=BaseDenom || !bankCoins.Amount.IsPositive() ||
       bankCoins.Amount.String()!=value.String() {return ErrBankSupplyMismatch}
    // This is for a newly initialized genesis state in an uncommitted cached
    // SDK context: a store write error MUST abort app initialization.
    if err:=kv.Set(keyGenesis,[]byte(value.String()));err!=nil {return err}
    if err:=kv.Set(keyLifetime,[]byte(value.String()));err!=nil {return err}
    return nil
}

func (k Keeper) read(ctx context.Context) (*big.Int,*big.Int,error) {
    kv,err:=k.kv(ctx)
    if err!=nil {return nil,nil,err}
    rawGenesis,err:=kv.Get(keyGenesis)
    if err!=nil {return nil,nil,err}
    rawLifetime,err:=kv.Get(keyLifetime)
    if err!=nil {return nil,nil,err}
    if rawGenesis==nil && rawLifetime==nil {return nil,nil,ErrNotInitialized}
    if rawGenesis==nil || rawLifetime==nil {return nil,nil,ErrStoreCorrupt}
    genesis,err:=parseCanonical(string(rawGenesis))
    if err!=nil {return nil,nil,ErrStoreCorrupt}
    lifetime,err:=parseCanonical(string(rawLifetime))
    if err!=nil {return nil,nil,ErrStoreCorrupt}
    if lifetime.Cmp(genesis)!=0 || lifetime.Cmp(capValue())>0 {
        return nil,nil,ErrStoreCorrupt
    }
    return genesis,lifetime,nil
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
    if _,_,err:=k.read(ctx);err!=nil {return err}
    for _,coin:=range coins {
        if coin.Denom==BaseDenom {
            return ErrMintForbidden
        }
    }
    return nil
}

// Reconcile rejects total bank native supply above the immutable genesis
// allocation. Burns may decrease outstanding supply but never increase budget.
// It does not detect unguarded intra-block mint+burn, hence it is NOT a complete
// substitute for protecting every mint path and unsafe setter.
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
    return nil
}

var _ banktypes.MintingRestrictionFn = (Keeper{}).MintRestriction
