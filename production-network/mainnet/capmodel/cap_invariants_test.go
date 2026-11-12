package capmodel

import (
    "errors"
    "math/big"
    "math/rand"
    "testing"
)

// This is an OFF-CHAIN model test. It does not exercise Cosmos SDK keepers,
// persisted consensus state, bank module mint permissions, or live validators.
func TestDeterministicAccountingSequence(t *testing.T) {
    const steps = 2000
    ledger := mustLedger(t, "1")
    capValue, ok := new(big.Int).SetString(MaximumBase, 10)
    if !ok { t.Fatal("invalid cap constant") }
    issued := big.NewInt(1)
    burned := big.NewInt(0)
    outstanding := big.NewInt(1)
    one := big.NewInt(1)
    rng := rand.New(rand.NewSource(20261112))

    assertState := func(step int) {
        t.Helper()
        snap := ledger.Snapshot()
        expectedRemaining := new(big.Int).Sub(capValue, issued)
        expectedOutstanding := new(big.Int).Sub(issued, burned)
        if issued.Cmp(capValue) > 0 || burned.Cmp(issued) > 0 ||
            expectedOutstanding.Sign() < 0 || outstanding.Cmp(expectedOutstanding) != 0 {
            t.Fatalf("step %d: internal reference accounting invalid", step)
        }
        if snap.GenesisBase != "1" || snap.Maximum != MaximumBase ||
            snap.LifetimeIssued != issued.String() || snap.Burned != burned.String() ||
            snap.Outstanding != outstanding.String() ||
            snap.RemainingToMint != expectedRemaining.String() {
            t.Fatalf("step %d: got %+v, want issued=%s burned=%s outstanding=%s remaining=%s",
                step, snap, issued, burned, outstanding, expectedRemaining)
        }
    }
    assertState(0)
    for step := 1; step <= steps; step++ {
        before := ledger.Snapshot()
        amount := big.NewInt(int64(rng.Intn(1000000) + 1))
        switch rng.Intn(5) {
        case 0, 1:
            if _, err := ledger.Mint(amount.String()); err != nil { t.Fatalf("step %d mint: %v", step, err) }
            issued.Add(issued, amount)
            outstanding.Add(outstanding, amount)
        case 2:
            if outstanding.Cmp(amount) >= 0 {
                if _, err := ledger.Burn(amount.String()); err != nil { t.Fatalf("step %d burn: %v", step, err) }
                burned.Add(burned, amount)
                outstanding.Sub(outstanding, amount)
            } else {
                if _, err := ledger.Burn(amount.String()); !errors.Is(err, ErrInsufficientSupply) {
                    t.Fatalf("step %d expected insufficient supply: %v", step, err)
                }
                if ledger.Snapshot() != before { t.Fatalf("step %d rejected burn mutated accounting", step) }
            }
        case 3:
            overflow := new(big.Int).Sub(capValue, issued)
            overflow.Add(overflow, one)
            if _, err := ledger.Mint(overflow.String()); !errors.Is(err, ErrLifetimeCapExceeded) {
                t.Fatalf("step %d expected cap rejection: %v", step, err)
            }
            if ledger.Snapshot() != before { t.Fatalf("step %d rejected mint mutated accounting", step) }
        case 4:
            if _, err := ledger.Mint("00"); !errors.Is(err, ErrInvalidAmount) {
                t.Fatalf("step %d expected invalid amount: %v", step, err)
            }
            if ledger.Snapshot() != before { t.Fatalf("step %d invalid mint mutated accounting", step) }
        }
        assertState(step)
    }
}

func TestRepeatedBurnCannotRestoreMintBudget(t *testing.T) {
    ledger := mustLedger(t, MaximumBase)
    for i := 0; i < 25; i++ {
        snap := ledger.Snapshot()
        if snap.Outstanding == "0" { break }
        burn := new(big.Int)
        burn.SetString(snap.Outstanding, 10)
        if burn.Cmp(big.NewInt(1)) > 0 { burn.Div(burn, big.NewInt(2)) }
        if _, err := ledger.Burn(burn.String()); err != nil { t.Fatal(err) }
        before := ledger.Snapshot()
        if _, err := ledger.Mint(burn.String()); !errors.Is(err, ErrLifetimeCapExceeded) {
            t.Fatalf("iteration %d: burn-and-remint unexpectedly allowed: %v", i, err)
        }
        if ledger.Snapshot() != before || before.RemainingToMint != "0" ||
            before.LifetimeIssued != MaximumBase {
            t.Fatalf("iteration %d: lifetime issuance changed after burn: %+v", i, ledger.Snapshot())
        }
    }
}
