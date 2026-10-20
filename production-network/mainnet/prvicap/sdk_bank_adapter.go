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

// The embedded interface is PRIVATE: other Go packages cannot dereference
// it to obtain the underlying concrete SDK BaseKeeper. Its exported Keeper
// methods remain promoted, except the unsafe methods we deliberately
// override below. A direct type assertion of ModuleRestrictedBank to SDK
// BaseKeeper will not succeed.
type sealedBankInterface interface { bankkeeper.Keeper }

// ModuleRestrictedBank is the SDK-compatible module banking dependency.
// The private interface promotes normal SDK bank methods; their original
// internal BaseKeeper receiver still handles ordinary transfers/delegations.
// We deny EXTERNAL UncheckedSetBalance calls for native aprvi, not the SDK's
// legitimate internal balance moves.
//
// This is a defensive module capability wrapper, NOT a complete SDK
// mutation authorization. The original raw BaseKeeper can still be retained
// elsewhere during app construction, SDK bank collections and direct KV
// writes may bypass it, and future module upgrades need review.
// No production PRVI mainnet is authorized.
type ModuleRestrictedBank struct {
    sealedBankInterface
}

// RestrictedBank attaches the immutable native PRVI mint restriction
// BEFORE any module receives its SDK banking dependency, and then blocks
// the publicly exposed unsafe PRVI balance setter on that dependency.
func RestrictedBank(bank bankkeeper.BaseKeeper, k Keeper) *ModuleRestrictedBank {
    return &ModuleRestrictedBank{sealedBankInterface: bank.WithMintCoinsRestriction(k.MintRestriction)}
}

// Module calls to UncheckedSetBalance must not modify native aprvi.
// Other test denominations preserve the pinned SDK's existing behavior.
func (bank *ModuleRestrictedBank) UncheckedSetBalance(
    ctx context.Context, address sdk.AccAddress, balance sdk.Coin,
) error {
    if balance.Denom == BaseDenom {
        return ErrDirectNativeBalanceForbidden
    }
    return bank.sealedBankInterface.UncheckedSetBalance(ctx, address, balance)
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
