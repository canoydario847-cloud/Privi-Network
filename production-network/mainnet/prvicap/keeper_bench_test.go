package prvicap

// This synthetic benchmark documents a known O(account balance records)
// consensus-block runtime cost. It DOES NOT certify production performance,
// provide an IAVL disk-backed block benchmark, or authorize financial mainnet.
//
// Run explicitly from production-network/mainnet/prvicap:
//   go test -run '^$' -bench '^BenchmarkNativeReconcileScaling$' -benchmem
//
// Includes unrelated denoms because IterateAllBalances reads *all* coins
// before the native aprvi filter; large multi-token sets can be expensive.

import (
    "context"
    "fmt"
    "testing"

    sdkmath "cosmossdk.io/math"
    sdk "github.com/cosmos/cosmos-sdk/types"
)

type syntheticBalanceWalk struct {
    rows []sdk.Coin
    expected sdkmath.Int
}
func (b syntheticBalanceWalk) GetSupply(_ context.Context, denom string) sdk.Coin {
    return sdk.NewCoin(denom,b.expected)
}
func (b syntheticBalanceWalk) IterateAllBalances(_ context.Context,
    visitor func(sdk.AccAddress,sdk.Coin) bool) {
    var address sdk.AccAddress = make([]byte,20)
    for _, coin := range b.rows {
        if visitor(address,coin) { return }
    }
}

func benchmarkBankRows(accounts int) syntheticBalanceWalk {
    rows:=make([]sdk.Coin,accounts+1)
    for i:=0;i<accounts;i++ {
        rows[i]=sdk.NewInt64Coin("atest",1)
    }
    rows[accounts]=sdk.NewInt64Coin(BaseDenom,100)
    return syntheticBalanceWalk{rows:rows,expected:sdkmath.NewInt(100)}
}

// BenchmarkNativeReconcileScaling measures the current conservation check's
// linear walk on 10/1,000/100,000 unrelated token-balance records. Benchmarks
// are NOT a simulation of real Cosmos SDK IAVL, multi-validator networking,
// gas throughput, finality or worst-case untrusted long-run state growth.
func BenchmarkNativeReconcileScaling(b *testing.B) {
    for _,accounts:=range []int{10,1000,100000} {
        b.Run(fmt.Sprintf("balance-records-%d",accounts),func(b *testing.B) {
            store:=newFakeKV()
            keeper,err:=New(fakeService{data:store})
            if err!=nil { b.Fatal(err) }
            ctx:=context.Background()
            bank:=benchmarkBankRows(accounts)
            if err=keeper.InitGenesis(ctx,"100",bank);err!=nil { b.Fatal(err) }
            b.ReportAllocs()
            b.ResetTimer()
            for n:=0;n<b.N;n++ {
                if err:=keeper.Reconcile(ctx,bank);err!=nil {b.Fatal(err)}
            }
        })
    }
}

// No output values are asserted as benchmarks vary across hosts. The
// corresponding CI command must never use a hardcoded milliseconds deadline.
