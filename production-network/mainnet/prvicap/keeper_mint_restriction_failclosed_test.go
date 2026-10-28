package prvicap

import (
    "context"
    "errors"
    "testing"

    sdk "github.com/cosmos/cosmos-sdk/types"
)

// These are keeper-level tests, NOT proof that every production module uses
// the restricted bank instance or that direct KV writes are impossible.
func TestNativeMintRestrictionFailsClosedWithoutStore(t *testing.T) {
    var keeper Keeper // intentionally unconfigured; no consensus store
    ctx := context.Background()
    for _, coins := range []sdk.Coins{
        sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1)),
        sdk.NewCoins(sdk.NewInt64Coin("uatom", 1), sdk.NewInt64Coin(BaseDenom, 1)),
    } {
        if err := keeper.MintRestriction(ctx, coins); err == nil {
            t.Fatalf("native mint permitted with unconfigured keeper: %v", coins)
        }
    }
    if err := keeper.MintRestriction(ctx, sdk.NewCoins(sdk.NewInt64Coin("uatom", 1))); err != nil {
        t.Fatalf("unrelated denomination unexpectedly blocked: %v", err)
    }
}

func TestNativeMintRestrictionRejectsNilContext(t *testing.T) {
    var keeper Keeper
    err := keeper.MintRestriction(nil, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1)))
    if err == nil {
        t.Fatal("native mint permitted with nil context")
    }
    if errors.Is(err, ErrMintForbidden) {
        t.Fatalf("unconfigured keeper must fail before policy check: %v", err)
    }
}
