package prvicap

import (
    "bytes"
    "testing"

    "cosmossdk.io/log/v2"
    "github.com/cosmos/cosmos-sdk/store/v2"
    storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
    sdk "github.com/cosmos/cosmos-sdk/types"
    authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
    cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
)

// TestAcceptanceRawKeeperDenialsSurviveCommittedStoreReopen is a two-store
// in-memory persistence acceptance. It is not a real process restart, a
// validator test, or proof against direct consensus KV writes/migrations.
func TestAcceptanceRawKeeperDenialsSurviveCommittedStoreReopen(t *testing.T) {
    requirePinnedSDKBankOverlay(t)
    h := newRealBankHarness(t)
    initPinnedSDKGenesisForAcceptance(t, h)

    original, err := h.cap.Snapshot(h.ctx)
    if err != nil { t.Fatal(err) }
    if original.GenesisBase != "100" || original.LifetimeIssuedBase != "100" {
        t.Fatalf("invalid initial issued-state fixture: %+v", original)
    }

    initial, ok := h.ctx.MultiStore().(storetypes.CommitMultiStore)
    if !ok { t.Fatal("missing commit-capable SDK multistore") }
    initial.Commit()

    // Reopen the actual committed bank and cap IAVL stores using a distinct
    // multistore instance, rather than merely reusing a cached SDK context.
    reopen := func(height int64) sdk.Context {
        t.Helper()
        cms := store.NewCommitMultiStore(h.db, log.NewNopLogger())
        cms.MountStoreWithDB(h.bankKey, storetypes.StoreTypeIAVL, h.bankDB)
        cms.MountStoreWithDB(h.capKey, storetypes.StoreTypeIAVL, h.capDB)
        cms.MountStoreWithDB(h.objKey, storetypes.StoreTypeObject, h.objDB)
        if err := cms.LoadLatestVersion(); err != nil { t.Fatal(err) }
        return sdk.NewContext(cms, cmtproto.Header{Height:height}, false, log.NewNopLogger())
    }
    restoredCtx := reopen(2)
    if s, err := h.cap.Snapshot(restoredCtx); err != nil || s != original {
        t.Fatalf("committed cap did not survive store reopen: %+v / %v", s, err)
    }
    if got := h.bank.GetSupply(restoredCtx, BaseDenom).Amount.String(); got != "100" {
        t.Fatalf("committed native supply was not restored: %s", got)
    }

    receiver := sdk.AccAddress(bytes.Repeat([]byte{0x73}, 20))
    minter := authtypes.NewEmptyModuleAccount("postrestartalias", authtypes.Minter)
    h.account.EXPECT().GetModuleAccount(restoredCtx, "postrestartalias").Return(minter).AnyTimes()
    if err := h.bank.UncheckedSetBalance(restoredCtx, receiver, sdk.NewInt64Coin(BaseDenom, 1)); err == nil {
        t.Error("NO-GO: raw keeper setter credited native units after reopen")
    }
    if err := h.bank.MintCoins(restoredCtx, "postrestartalias",
        sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); err == nil {
        t.Error("NO-GO: raw keeper minted PRVI after reopen")
    }
    if got := h.bank.GetBalance(restoredCtx, receiver, BaseDenom).Amount; !got.IsZero() {
        t.Errorf("NO-GO: rejected raw setter altered account: %s", got)
    }
    if got := h.bank.GetBalance(restoredCtx, minter.GetAddress(), BaseDenom).Amount; !got.IsZero() {
        t.Errorf("NO-GO: rejected raw mint credited module: %s", got)
    }
    if got := h.bank.GetSupply(restoredCtx, BaseDenom).Amount.String(); got != "100" {
        t.Errorf("NO-GO: native supply changed after invalid operations: %s", got)
    }
    if s, err := h.cap.Snapshot(restoredCtx); err != nil || s != original {
        t.Errorf("NO-GO: native lifetime-issuance state changed: %+v / %v", s, err)
    }

    // Commit the attempted operations, reopen from the DB, then repeat
    // observations. This detects writes that only become visible later.
    afterAttempt, ok := restoredCtx.MultiStore().(storetypes.CommitMultiStore)
    if !ok { t.Fatal("reopened multistore cannot commit") }
    afterAttempt.Commit()
    finalCtx := reopen(3)
    if got := h.bank.GetSupply(finalCtx, BaseDenom).Amount.String(); got != "100" {
        t.Errorf("NO-GO: denied mint persisted supply change: %s", got)
    }
    if got := h.bank.GetBalance(finalCtx, receiver, BaseDenom).Amount; !got.IsZero() {
        t.Errorf("NO-GO: denied setter persisted unauthorized balance: %s", got)
    }
    if got := h.bank.GetBalance(finalCtx, minter.GetAddress(), BaseDenom).Amount; !got.IsZero() {
        t.Errorf("NO-GO: denied mint persisted module balance: %s", got)
    }
    if s, err := h.cap.Snapshot(finalCtx); err != nil || s != original {
        t.Errorf("NO-GO: immutable issuance did not survive second reopen: %+v / %v", s, err)
    }
    if err := h.cap.Reconcile(finalCtx, h.bank); err != nil {
        t.Errorf("NO-GO: restored account/supply conservation failed: %v", err)
    }
}
