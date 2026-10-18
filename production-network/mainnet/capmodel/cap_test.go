package capmodel

import (
    "errors"
    "math/big"
    "sync"
    "testing"
)

func pow18(coins int64) string {
    return new(big.Int).Mul(big.NewInt(coins), big.NewInt(1_000_000_000_000_000_000)).String()
}
func mustLedger(t *testing.T, genesis string) *Ledger {
    t.Helper()
    l, err := New(genesis)
    if err != nil { t.Fatalf("New(%q): %v", genesis, err) }
    return l
}
func TestConstants(t *testing.T) {
    if MaximumPRVI != "1000000000" || MaximumBase != pow18(1_000_000_000) ||
        BaseDenom != "aprvi" || Symbol != "PRVI" || Decimals != 18 {
        t.Fatal("PRVI policy constants differ from proposed spec")
    }
}
func TestZeroAndInvalidGenesis(t *testing.T) {
    for _, raw := range []string{"0", "", "-1", "+1", "001", "1.0", " 1", "1\n", "１", "0x1",
        "1000000000000000000000000001"} {
        if _, err := New(raw); !errors.Is(err, ErrInvalidGenesis) {
            t.Fatalf("Genesis %q should be rejected, got %v", raw, err)
        }
    }
}
func TestFullCapGenesisMintImpossible(t *testing.T) {
    l := mustLedger(t, MaximumBase)
    before := l.Snapshot()
    if _, err := l.Mint("1"); !errors.Is(err, ErrLifetimeCapExceeded) {
        t.Fatalf("should reject extra 1 base unit: %v", err)
    }
    if l.Snapshot() != before { t.Fatal("rejected mint mutated supply") }
}
func TestPartialGenesisMayIssueOnlyRemaining(t *testing.T) {
    l := mustLedger(t, pow18(500_000_000))
    next, err := l.Mint(pow18(500_000_000))
    if err != nil { t.Fatal(err) }
    if next.RemainingToMint != "0" || next.LifetimeIssued != MaximumBase || next.Outstanding != MaximumBase {
        t.Fatalf("cap boundary wrong: %+v", next)
    }
    if _, err := l.Mint("1"); !errors.Is(err, ErrLifetimeCapExceeded) { t.Fatal(err) }
}
func TestBurnNeverReopensIssuanceCap(t *testing.T) {
    l := mustLedger(t, MaximumBase)
    after, err := l.Burn(pow18(100_000_000))
    if err != nil { t.Fatal(err) }
    if after.Outstanding != pow18(900_000_000) ||
        after.Burned != pow18(100_000_000) ||
        after.LifetimeIssued != MaximumBase || after.RemainingToMint != "0" {
        t.Fatalf("burn unexpectedly reopened minting: %+v", after)
    }
    if _, err := l.Mint("1"); !errors.Is(err, ErrLifetimeCapExceeded) { t.Fatal(err) }
}
func TestPartialMintThenBurnStillCountsLifetime(t *testing.T) {
    l := mustLedger(t, pow18(400_000_000))
    if _, err := l.Mint(pow18(100_000_000)); err != nil { t.Fatal(err) }
    if _, err := l.Burn(pow18(300_000_000)); err != nil { t.Fatal(err) }
    result := l.Snapshot()
    if result.LifetimeIssued != pow18(500_000_000) ||
       result.Outstanding != pow18(200_000_000) ||
       result.RemainingToMint != pow18(500_000_000) { t.Fatalf("%+v", result) }
    if _, err := l.Mint(pow18(500_000_000)); err != nil { t.Fatal(err) }
    if _, err := l.Mint("1"); !errors.Is(err, ErrLifetimeCapExceeded) { t.Fatal(err) }
}
func TestInvalidMintAndBurnAtomic(t *testing.T) {
    l := mustLedger(t, pow18(7))
    original := l.Snapshot()
    for _, raw := range []string{"", "0", "-1", "+1", "01", "1.0", "1e18", " 5", "１２"} {
        if _, err := l.Mint(raw); !errors.Is(err, ErrInvalidAmount) {
            t.Fatalf("Mint %q returned %v", raw, err)
        }
        if _, err := l.Burn(raw); !errors.Is(err, ErrInvalidAmount) {
            t.Fatalf("Burn %q returned %v", raw, err)
        }
    }
    if _, err := l.Burn(pow18(8)); !errors.Is(err, ErrInsufficientSupply) { t.Fatal(err) }
    if l.Snapshot() != original { t.Fatal("failed transactions modified balances") }
}
func TestHugeDecimalDoesNotOverflowAndIsRejected(t *testing.T) {
    l := mustLedger(t, "1")
    large := "1"
    for i := 0; i < 120; i++ { large += "0" }
    if _, err := l.Mint(large); !errors.Is(err, ErrLifetimeCapExceeded) { t.Fatal(err) }
    if got := l.Snapshot().Outstanding; got != "1" { t.Fatal(got) }
}
func TestConcurrentMintNeverExceedsHardCap(t *testing.T) {
    l := mustLedger(t, pow18(999_999_999))
    // Parallel minting of 2 base units each until exactly 1 PRVI can be
    // distributed. Check atomicity and no over-cap issue.
    const num = 100
    amount := new(big.Int).Div(big.NewInt(1_000_000_000_000_000_000),big.NewInt(num)).String()
    var wg sync.WaitGroup
    errorsCh := make(chan error, num)
    for i := 0; i < num; i++ {
        wg.Add(1)
        go func() {
            defer wg.Done()
            _, err := l.Mint(amount)
            errorsCh <- err
        }()
    }
    wg.Wait()
    close(errorsCh)
    for err := range errorsCh { if err != nil { t.Fatal(err) } }
    if l.Snapshot().LifetimeIssued != MaximumBase { t.Fatal("parallel mint lost accounting") }
    if _, err := l.Mint("1"); !errors.Is(err, ErrLifetimeCapExceeded) { t.Fatal(err) }
}
func TestSnapshotDoesNotLeakMutableState(t *testing.T) {
    l := mustLedger(t, pow18(5))
    snapshot := l.Snapshot()
    snapshot.Outstanding = "9999999999999999999999999999999"
    if l.Snapshot().Outstanding != pow18(5) { t.Fatal("external snapshot mutated ledger") }
}
