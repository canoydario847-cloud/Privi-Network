package prvicap

import bankkeeper "github.com/cosmos/cosmos-sdk/x/bank/keeper"

// RestrictedBank is the exact pinned Cosmos SDK v0.54.3 extension point.
// IMPORTANT: Call once immediately after constructing the app's bank keeper,
// BEFORE handing it to mint, ERC20, VM, staking, transfer or other modules.
// This returns a VALUE COPY of BaseKeeper with the restriction installed;
// older, unrestricted copies must never be used or retained.
//
// Also guard UncheckedSetBalance, module upgrades, and other supply-changing
// paths separately. A bank-level MintCoins restriction alone is not a
// comprehensive audited financial chain and remains NOT DEPLOYED.
func RestrictedBank(bank bankkeeper.BaseKeeper, k Keeper) bankkeeper.BaseKeeper {
    return bank.WithMintCoinsRestriction(k.MintRestriction)
}
