package prvicap

import (
    "context"
    "errors"

    storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
    sdk "github.com/cosmos/cosmos-sdk/types"
    bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
    banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
)

// ErrDirectNativeBalanceForbidden stops an ordinary module from bypassing
// the native PRVI issuance restrictions using a public unsafe setter.
// This is NOT a solution to malicious source changes or direct consensus
// store access. A fully audited bank mutation policy is still required.
var ErrDirectNativeBalanceForbidden = errors.New(
    "PRVI native bank balance cannot be changed through an unchecked external setter",
)

// ModuleRestrictedBank is the bankkeeper.Keeper used by the experimental
// Privi application when injecting bank access into SDK/EVM modules.
//
// Methods of the embedded SDK keeper implement normal, audited-by-upstream
// transfer and delegation behavior. Its low-level methods internally call
// their original SDK BaseKeeper receiver: this override is an additional
// denial only for external UncheckedSetBalance calls, not a new mint right.
//
// WARNING: This embedded BaseKeeper remains accessible through Go type
// assertion and is only a defense-in-depth test prototype. Any extra raw
// keeper copy or direct KV/collection write can bypass it. No production
// PRVI mainnet is authorized.
type ModuleRestrictedBank struct {
    bankkeeper.BaseKeeper
}

// RestrictedBank attaches the immutable native PRVI mint restriction
// BEFORE any module receives its SDK banking dependency, and then blocks
// the publicly exposed unsafe PRVI balance setter on that dependency.
func RestrictedBank(bank bankkeeper.BaseKeeper, k Keeper) *ModuleRestrictedBank {
    return &ModuleRestrictedBank{BaseKeeper: bank.WithMintCoinsRestriction(k.MintRestriction)}
}

// Module calls to UncheckedSetBalance must not modify native aprvi.
// Other test denominations preserve the pinned SDK's existing behavior.
func (bank *ModuleRestrictedBank) UncheckedSetBalance(
    ctx context.Context, address sdk.AccAddress, balance sdk.Coin,
) error {
    if balance.Denom == BaseDenom {
        return ErrDirectNativeBalanceForbidden
    }
    return bank.BaseKeeper.UncheckedSetBalance(ctx, address, balance)
}

// These builder methods return an SDK BaseKeeper by value. Allowing a
// module to invoke them on the wrapped dependency would return an object
// without the external unsafe-setter override. Fail closed rather than
// leaking such a copy. The application must apply WithObjStoreKey before
// RestrictedBank and must never configure new mint restrictions later.
func (bank *ModuleRestrictedBank) WithMintCoinsRestriction(
    _ banktypes.MintingRestrictionFn,
) bankkeeper.BaseKeeper {
    panic("PRVI bank: cannot derive module-owned SDK bank keeper copy")
}

func (bank *ModuleRestrictedBank) WithObjStoreKey(
    _ storetypes.StoreKey,
) bankkeeper.BaseKeeper {
    panic("PRVI bank: bank object store must be configured before restriction")
}

var _ bankkeeper.Keeper = (*ModuleRestrictedBank)(nil)
