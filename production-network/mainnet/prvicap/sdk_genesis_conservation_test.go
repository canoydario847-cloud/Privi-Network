package prvicap

import (
    "errors"
    "testing"

    authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
    sdk "github.com/cosmos/cosmos-sdk/types"
)

// The real SDK's unsafe balance setter can modify native account balances
// without adjusting x/bank's supply counter. Genesis must reject that split
// before writing the immutable lifetime issuance record.
func TestActualSDKBankGenesisRejectsUntrackedNativeBalanceWrites(t *testing.T) {
    for _, tc := range []struct {
        name string
        actual int64
    }{
        {name: "extra native units", actual: 101},
        {name: "missing native units", actual: 99},
        {name: "all native units removed", actual: 0},
    } {
        t.Run(tc.name, func(t *testing.T) {
            h := newRealBankHarness(t)
            h.genesisFund(t, 100)
            address := authtypes.NewModuleAddress("genesisfixture")
            if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin(BaseDenom, tc.actual)); err != nil {
                t.Fatalf("could not arrange untracked native balance change: %v", err)
            }
            if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != "100" {
                t.Fatalf("test precondition: bank supply changed unexpectedly to %s", got)
            }
            if err := h.cap.InitGenesis(h.ctx, "100", h.bank); !errors.Is(err, ErrBankSupplyMismatch) {
                t.Fatalf("untracked balance change was not rejected: %v", err)
            }
            if _, err := h.cap.Snapshot(h.ctx); !errors.Is(err, ErrNotInitialized) {
                t.Fatalf("rejected genesis persisted a cap record: %v", err)
            }
            if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrNotInitialized) {
                t.Fatalf("native mint did not fail closed after rejected genesis: %v", err)
            }

            // A corrected, matching bank state must still be able to
            // initialize exactly once; the failed attempt left no cap state.
            if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin(BaseDenom, 100)); err != nil {
                t.Fatalf("could not restore fixture balance: %v", err)
            }
            if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil {
                t.Fatalf("corrected matching bank state rejected: %v", err)
            }
            if state, err := h.cap.Snapshot(h.ctx); err != nil || state.GenesisBase != "100" {
                t.Fatalf("corrected genesis state invalid: %+v, %v", state, err)
            }
            // A failed genesis attempt must not permit a later caller to
            // rewrite the successfully initialized lifetime issuance record.
            if err := h.cap.InitGenesis(h.ctx, "99", h.bank); !errors.Is(err, ErrAlreadyInitialized) {
                t.Fatalf("second genesis initialization was not refused: %v", err)
            }
            if state, err := h.cap.Snapshot(h.ctx); err != nil ||
                state.GenesisBase != "100" || state.LifetimeIssuedBase != "100" {
                t.Fatalf("second genesis attempt changed issuance record: %+v, %v", state, err)
            }
            if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
                t.Fatalf("native mint not forbidden after successful initialization: %v", err)
            }
        })
    }
}
