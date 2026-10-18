package prvicap

import (
    "errors"
    "testing"

    sdkmath "cosmossdk.io/math"
    sdk "github.com/cosmos/cosmos-sdk/types"
    authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
)

// TestActualSDKBankGenesisCapBoundary exercises the REAL SDK bank keeper
// against the proposed 1,000,000,000 PRVI / 10^27 aprvi maximum. The
// genesis balance is arranged only in a disposable in-memory SDK fixture.
// No financial chain, actual PRVI issuance, keys, or network are involved.
func TestActualSDKBankGenesisCapBoundary(t *testing.T) {
    for _, tc := range []struct {
        name string
        genesis string
        accepted bool
    }{
        {name: "exactly_one_billion_whole_prvi", genesis: MaxBase, accepted: true},
        {name: "one_base_unit_above_cap", genesis: "1000000000000000000000000001", accepted: false},
    } {
        t.Run(tc.name, func(t *testing.T) {
            h := newRealBankHarness(t)
            amount, ok := sdkmath.NewIntFromString(tc.genesis)
            if !ok { t.Fatal("invalid test fixture") }
            fixture := authtypes.NewEmptyModuleAccount("genesisboundary", authtypes.Minter)
            h.account.EXPECT().GetModuleAccount(h.ctx, "genesisboundary").Return(fixture)
            if err := h.bank.MintCoins(h.ctx, "genesisboundary", sdk.NewCoins(sdk.NewCoin(BaseDenom, amount))); err != nil {
                t.Fatalf("failed to arrange valueless in-memory bank supply: %v", err)
            }
            if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != tc.genesis {
                t.Fatalf("SDK bank fixture mismatch: got %s want %s", got, tc.genesis)
            }
            err := h.cap.InitGenesis(h.ctx, tc.genesis, h.bank)
            restricted := RestrictedBank(h.bank, h.cap)
            if tc.accepted {
                if err != nil { t.Fatalf("cap-boundary genesis rejected: %v", err) }
                state, err := h.cap.Snapshot(h.ctx)
                if err != nil { t.Fatal(err) }
                if state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
                    t.Fatalf("incorrect persisted issuance: %+v", state)
                }
                if err := restricted.MintCoins(h.ctx, "mint", sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
                    t.Fatalf("one extra base unit was not denied: %v", err)
                }
                if got := restricted.GetSupply(h.ctx, BaseDenom).Amount.String(); got != MaxBase {
                    t.Fatalf("rejected mint changed bank supply: %s", got)
                }
                // Confirm the maximum immutable issuance survives an actual
                // multistore commit/reopen, not merely a keeper object reset.
                ctx2, bank2, cap2 := h.restart(t)
                snapshot2, err := cap2.Snapshot(ctx2)
                if err != nil { t.Fatal(err) }
                if snapshot2 != state { t.Fatalf("reopened cap changed: got %+v want %+v", snapshot2, state) }
                if got := bank2.GetSupply(ctx2, BaseDenom).Amount.String(); got != MaxBase {
                    t.Fatalf("reopened bank lost maximum genesis supply: %s", got)
                }
                if err := bank2.MintCoins(ctx2, "mint", sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
                    t.Fatalf("post-restart mint allowed at cap: %v", err)
                }
            } else {
                if !errors.Is(err, ErrInvalidGenesis) { t.Fatalf("over-cap genesis accepted: %v", err) }
                if _, err := h.cap.Snapshot(h.ctx); !errors.Is(err, ErrNotInitialized) {
                    t.Fatalf("invalid genesis persisted cap state: %v", err)
                }
                if err := restricted.MintCoins(h.ctx, "mint", sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrNotInitialized) {
                    t.Fatalf("over-cap state allowed native mint: %v", err)
                }
                if got := restricted.GetSupply(h.ctx, BaseDenom).Amount.String(); got != tc.genesis {
                    t.Fatalf("rejected mint changed bank supply: %s", got)
                }
            }
        })
    }
}
