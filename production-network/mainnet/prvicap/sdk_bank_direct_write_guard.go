package prvicap

// RestrictDirectNativeWrites narrows a known Cosmos SDK balance-accounting
// escape hatch: modules receiving the app's exposed bankkeeper.Keeper must
// not directly rewrite a native aprvi account balance without supply updates
// and transfer authorization.
//
// This is DEFENSE IN DEPTH, not a complete prevention of supply-neutral
// forgery. The embedded SDK BaseKeeper's own normal SendCoins/Delegate/
// BurnCoins implementation uses its internal base receiver, so legitimate
// SDK accounting paths remain unchanged. Other raw BaseKeeper copies,
// .WithMintCoinsRestriction/.WithObjStoreKey unwrapping, direct consensus-KV
// writes and unreviewed module/VM pathways remain launch-blocking risks.

import (
    "context"
    "errors"

    sdk "github.com/cosmos/cosmos-sdk/types"
    bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"
)

var ErrDirectNativeBalanceWriteForbidden = errors.New(
    "PRVI native aprvi direct balance setter forbidden; use authorized bank execution path",
)

type directNativeWriteGuard struct {
    bankkeeper.BaseKeeper
}

var _ bankkeeper.Keeper = directNativeWriteGuard{}

// UncheckedSetBalance is explicitly part of the upstream Keeper interface.
// Do not expose a writable raw BaseKeeper to unreviewed modules. This blocks
// native account rewrites even when the change preserves aggregate supply.
func (b directNativeWriteGuard) UncheckedSetBalance(
    ctx context.Context, addr sdk.AccAddress, coin sdk.Coin,
) error {
    if coin.Denom == BaseDenom {
        return ErrDirectNativeBalanceWriteForbidden
    }
    return b.BaseKeeper.UncheckedSetBalance(ctx, addr, coin)
}

// BankForApp constructs the public module-facing keeper with native mint
// restriction plus direct unchecked-balance-setter interception. The caller
// must not retain or pass the raw constructor result to any other module.
func BankForApp(base bankkeeper.BaseKeeper, cap Keeper) bankkeeper.Keeper {
    return directNativeWriteGuard{BaseKeeper: RestrictedBank(base, cap)}
}
