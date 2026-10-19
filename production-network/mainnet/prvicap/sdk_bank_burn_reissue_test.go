package prvicap

// This test exercises the actual Cosmos SDK v0.54.3 x/bank keeper.
// It uses disposable in-memory coins only. NO deployable PRVI is created.
import (
    "errors"
    "testing"

    sdk "github.com/cosmos/cosmos-sdk/types"
    authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
)

func TestActualSDKBurnCannotUnlockNativeReissuance(t *testing.T) {
    h := newRealBankHarness(t)
    const initial int64 = 100
    const burn int64 = 40
    const afterBurn int64 = initial - burn

    burnModule := authtypes.NewEmptyModuleAccount(
        "genesisburn", authtypes.Minter, authtypes.Burner,
    )
    // Real SDK bank MintCoins and BurnCoins both resolve the module account.
    // The restricted bank must refuse post-genesis issuance even though the
    // burner reduces circulating supply and therefore unused headroom exists.
    h.account.EXPECT().GetModuleAccount(h.ctx, "genesisburn").
        Return(burnModule).AnyTimes()
    // In SDK v0.54.3 BurnCoins checks spendability with LockedCoins,
    // which calls AccountKeeper.GetAccount for this module address.
    // The test harness uses a strict gomock account keeper.
    h.account.EXPECT().GetAccount(h.ctx, burnModule.GetAddress()).
        Return(burnModule).AnyTimes()
    if err := h.bank.MintCoins(h.ctx, "genesisburn",
        sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, initial))); err != nil {
        t.Fatalf("setup disposable initial PRVI supply: %v", err)
    }
    if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil {
        t.Fatalf("initialize immutable issuance record: %v", err)
    }
    k := RestrictedBank(h.bank, h.cap)
    if err := k.BurnCoins(h.ctx, "genesisburn",
        sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, burn))); err != nil {
        t.Fatalf("real SDK bank burn failed: %v", err)
    }
    if got := k.GetSupply(h.ctx, BaseDenom).Amount.Int64(); got != afterBurn {
        t.Fatalf("native supply after burn = %d, want %d", got, afterBurn)
    }
    if err := h.cap.Reconcile(h.ctx, k); err != nil {
        t.Fatalf("honest burn should preserve bank conservation: %v", err)
    }
    if err := k.MintCoins(h.ctx, "genesisburn",
        sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
        t.Fatalf("burn must NOT make room for native reissuance: %v", err)
    }
    before, err := h.cap.Snapshot(h.ctx)
    if err != nil { t.Fatal(err) }
    if before.LifetimeIssuedBase != "100" || before.GenesisBase != "100" {
        t.Fatalf("burn changed immutable issuance accounting: %+v", before)
    }

    // Reopen the actual SDK database and verify the rule survives restart,
    // not just a process-local simulation or fake keeper.
    restartedCtx, restartedBank, restartedCap := h.restart(t)
    after, err := restartedCap.Snapshot(restartedCtx)
    if err != nil || after != before {
        t.Fatalf("restart changed immutable issuance: %+v / %v", after, err)
    }
    if got := restartedBank.GetSupply(restartedCtx, BaseDenom).Amount.Int64(); got != afterBurn {
        t.Fatalf("reopened bank lost the burn state: %d", got)
    }
    if err := restartedBank.MintCoins(restartedCtx, "genesisburn",
        sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
        t.Fatalf("restarted guarded bank allowed post-burn remint: %v", err)
    }
    if err := restartedCap.Reconcile(restartedCtx, restartedBank); err != nil {
        t.Fatalf("post-restart bank/cap reconciliation: %v", err)
    }
}
