package prvicap

// Real Cosmos SDK v0.54.3 bank keeper and IAVL-backed multistore benchmark.
// Unlike BenchmarkNativeReconcileScaling, this is NOT a fake BankView: it
// inserts many unrelated token accounts with the actual SDK balance setter
// and then exercises the real bank.IterateAllBalances from cap.Reconcile.
//
// Limitations: ephemeral MemDB, uncommitted cache, one CPU runner, no IAVL
// historical versions, disk I/O, CometBFT network, P2P/EVM load or host
// failure testing. Even good runner times do NOT authorize financial PRVI.

import (
    "encoding/binary"
    "fmt"
    "testing"

    sdk "github.com/cosmos/cosmos-sdk/types"
)

// Separate h for each variant ensures SDK store versions and account counts
// cannot mix across benchmark cases. Unlike signed financial mainnet, these
// dummy accounts contain no signing keys and no actual funded PRVI.
func BenchmarkActualSDKNativeConservationScan(b *testing.B) {
    for _,accounts:=range []int{100,1000,5000} {
        b.Run(fmt.Sprintf("iavl-account-records-%d",accounts),func(b *testing.B) {
            b.StopTimer()
            h:=newRealBankHarness(b)
            h.genesisFund(b,100)
            if err:=h.cap.InitGenesis(h.ctx,"100",h.bank);err!=nil { b.Fatal(err) }
            for i:=0;i<accounts;i++ {
                addr:=make([]byte,20)
                binary.BigEndian.PutUint64(addr[12:],uint64(i+1))
                if err:=h.bank.UncheckedSetBalance(
                    h.ctx,sdk.AccAddress(addr),
                    sdk.NewInt64Coin("atest",1),
                );err!=nil { b.Fatalf("insert disposable nonnative balance: %v",err) }
            }
            // The synthetic balances intentionally don't change x/bank supply
            // for "atest"; this benchmark solely measures the native PRVI
            // Reconcile consistency scan, not general total-denom conservation.
            if err:=h.cap.Reconcile(h.ctx,h.bank);err!=nil {
                b.Fatalf("pre-benchmark SDK PRVI conservation: %v",err)
            }
            b.ReportAllocs()
            b.ResetTimer()
            // ResetTimer clears the elapsed time but leaves a stopped
            // benchmark stopped. StartTimer is mandatory; otherwise Go
            // prints NO ns/op and an apparently successful zero-allocation
            // benchmark that did not actually measure this SDK/IAVL walk.
            b.StartTimer()
            for i:=0;i<b.N;i++ {
                if err:=h.cap.Reconcile(h.ctx,h.bank);err!=nil {b.Fatal(err)}
            }
        })
    }
}
