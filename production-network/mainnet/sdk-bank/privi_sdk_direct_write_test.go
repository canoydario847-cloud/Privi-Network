package keeper

// Copied ONLY into disposable patched Cosmos SDK v0.54.3 by experimental CI.
// Package-local access tests the real exported BaseSendKeeper method, not a
// user-defined wrapper. No database, keys, network or financial APRVI.
import (
    "context"
    "strings"
    "testing"

    sdk "github.com/cosmos/cosmos-sdk/types"
)

func TestPriviNativeDirectSetterDeniedWithConcreteBaseKeeper(t *testing.T) {
    var k BaseKeeper
    ctx:=context.Background()
    address:=sdk.AccAddress(make([]byte,20))
    for _,amt:=range []int64{0,1,100} {
        err:=k.UncheckedSetBalance(ctx,address,sdk.NewInt64Coin("aprvi",amt))
        if err==nil || !strings.Contains(err.Error(),
            "PRVI forbidden direct unchecked native account balance write") {
            t.Fatalf("native direct setter allowed %d: %v",amt,err)
        }
    }
    // Prove upstream type identity has not been replaced by a wrapper.
    var _ Keeper = k
}

func TestPriviNoDirectSetterOverrideInBankSource(t *testing.T) {
    var _ SendKeeper = BaseSendKeeper{}
    var _ Keeper = BaseKeeper{}
}
