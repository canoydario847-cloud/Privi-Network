package prvicap

import (
    "errors"
    "math/big"
    "testing"

    sdkmath "cosmossdk.io/math"
    banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"

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


// The proposed 1B PRVI / 18-decimal boundary must survive the actual SDK
// bank genesis path and the independent consensus-backed cap keeper, not
// merely the fake bank view or a constant comparison.
func TestActualSDKBankGenesisAtOneBillionPRVIBoundary(t *testing.T) {
    h := newRealBankHarness(t)
    max, ok := new(big.Int).SetString(MaxBase, 10)
    if !ok { t.Fatal("invalid embedded PRVI maximum") }
    amount := sdkmath.NewIntFromBigInt(max)
    allocation := sdk.NewCoins(sdk.NewCoin(BaseDenom, amount))
    address := authtypes.NewModuleAddress("genesisfixture")
    h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
        Params: banktypes.DefaultParams(),
        Balances: []banktypes.Balance{{Address: address.String(), Coins: allocation}},
        Supply: allocation,
    })
    if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount; !got.Equal(amount) {
        t.Fatalf("real SDK bank truncated native cap: got %s", got)
    }
    if err := h.cap.InitGenesis(h.ctx, MaxBase, h.bank); err != nil {
        t.Fatalf("exact-cap genesis rejected by keeper: %v", err)
    }
    if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
        t.Fatalf("exact-cap SDK balances failed reconciliation: %v", err)
    }
    state, err := h.cap.Snapshot(h.ctx)
    if err != nil || state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
        t.Fatalf("exact-cap issuance record incorrect: %+v, %v", state, err)
    }
    if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
        t.Fatalf("new native mint accepted at cap: %v", err)
    }
}


// TestActualSDKBankGenesisRejectsAboveOneBillionPRVIBoundary verifies that
// a real SDK bank genesis with one aprvi beyond the proposed maximum cannot
// initialize the cap keeper, even if its declared supply matches its balances.
// A caller also cannot hide the extra unit by claiming the exact maximum.
func TestActualSDKBankGenesisRejectsAboveOneBillionPRVIBoundary(t *testing.T) {
	h := newRealBankHarness(t)
	max, ok := new(big.Int).SetString(MaxBase, 10)
	if !ok {
		t.Fatal("invalid embedded PRVI maximum")
	}
	over := new(big.Int).Add(max, big.NewInt(1))
	amount := sdkmath.NewIntFromBigInt(over)
	allocation := sdk.NewCoins(sdk.NewCoin(BaseDenom, amount))
	address := authtypes.NewModuleAddress("genesisfixture")
	h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
		Params:   banktypes.DefaultParams(),
		Balances: []banktypes.Balance{{Address: address.String(), Coins: allocation}},
		Supply:   allocation,
	})
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount; !got.Equal(amount) {
		t.Fatalf("test precondition: SDK bank supply differs from over-cap balance: %s", got)
	}
	if err := h.cap.InitGenesis(h.ctx, over.String(), h.bank); !errors.Is(err, ErrInvalidGenesis) {
		t.Fatalf("above-cap native genesis was not rejected: %v", err)
	}
	if err := h.cap.InitGenesis(h.ctx, MaxBase, h.bank); !errors.Is(err, ErrBankSupplyMismatch) {
		t.Fatalf("underdeclared over-cap native bank supply was not rejected: %v", err)
	}
	if _, err := h.cap.Snapshot(h.ctx); !errors.Is(err, ErrNotInitialized) {
		t.Fatalf("rejected over-cap genesis persisted issuance: %v", err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrNotInitialized) {
		t.Fatalf("native mint did not fail closed after rejected over-cap genesis: %v", err)
	}
}

// TestActualSDKBankGenesisDistributedExactCap verifies that a full-cap
// allocation split across distinct SDK bank accounts is conserved exactly.
// A one-aprvi remainder makes off-by-one summation errors observable.
func TestActualSDKBankGenesisDistributedExactCap(t *testing.T) {
	h := newRealBankHarness(t)
	max, ok := new(big.Int).SetString(MaxBase, 10)
	if !ok {
		t.Fatal("invalid embedded PRVI maximum")
	}
	remaining := new(big.Int).Sub(max, big.NewInt(1))
	first := sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))
	second := sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(remaining)))
	supply := sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max)))
	firstAddr := authtypes.NewModuleAddress("genesisfixtureone")
	secondAddr := authtypes.NewModuleAddress("genesisfixturetwo")
	h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
		Params: banktypes.DefaultParams(),
		Balances: []banktypes.Balance{
			{Address: firstAddr.String(), Coins: first},
			{Address: secondAddr.String(), Coins: second},
		},
		Supply: supply,
	})
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.BigInt(); got.Cmp(max) != 0 {
		t.Fatalf("distributed SDK bank supply differs from exact cap: %s", got)
	}
	if err := h.cap.InitGenesis(h.ctx, MaxBase, h.bank); err != nil {
		t.Fatalf("distributed exact-cap genesis rejected: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("distributed exact-cap balances failed reconciliation: %v", err)
	}
	state, err := h.cap.Snapshot(h.ctx)
	if err != nil || state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
		t.Fatalf("distributed exact-cap issuance record incorrect: %+v, %v", state, err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
		t.Fatalf("distributed exact-cap genesis allowed native mint: %v", err)
	}
	// The bank supply counter can remain at the cap while an unchecked
	// account write makes the actual distributed allocation exceed it.
	if err := h.bank.UncheckedSetBalance(h.ctx, firstAddr, sdk.NewInt64Coin(BaseDenom, 2)); err != nil {
		t.Fatalf("could not arrange untracked distributed unit: %v", err)
	}
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.BigInt(); got.Cmp(max) != 0 {
		t.Fatalf("test precondition: declared bank supply changed: %s", got)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
		t.Fatalf("distributed untracked unit escaped conservation check: %v", err)
	}
	if state, err := h.cap.Snapshot(h.ctx); err != nil || state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
		t.Fatalf("failed reconciliation altered issuance record: %+v, %v", state, err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, firstAddr, sdk.NewInt64Coin(BaseDenom, 1)); err != nil {
		t.Fatalf("could not restore distributed fixture: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("restored distributed exact-cap allocation failed reconciliation: %v", err)
	}
	// A missing unit in the second account must also fail conservation.
	// This is not a mint or burn: the bank supply counter is unchanged.
	missing := new(big.Int).Sub(remaining, big.NewInt(1))
	if err := h.bank.UncheckedSetBalance(h.ctx, secondAddr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(missing))); err != nil {
		t.Fatalf("could not arrange untracked distributed deficit: %v", err)
	}
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.BigInt(); got.Cmp(max) != 0 {
		t.Fatalf("test precondition: declared supply changed during deficit: %s", got)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
		t.Fatalf("distributed missing unit escaped conservation check: %v", err)
	}
	if state, err := h.cap.Snapshot(h.ctx); err != nil || state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
		t.Fatalf("deficit reconciliation altered issuance record: %+v, %v", state, err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
		t.Fatalf("distributed deficit allowed native mint: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, secondAddr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(remaining))); err != nil {
		t.Fatalf("could not restore second distributed account: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("restored distributed deficit failed reconciliation: %v", err)
	}
}

// TestActualSDKBankBelowCapRejectsUntrackedBoundaryUnit checks that a bank
// supply just below the lifetime maximum cannot hide an unchecked balance
// increase of one aprvi, even though the actual balances reach (not exceed)
// the 1B PRVI cap. Conservation and issuance are separate invariants.
func TestActualSDKBankBelowCapRejectsUntrackedBoundaryUnit(t *testing.T) {
	h := newRealBankHarness(t)
	max, ok := new(big.Int).SetString(MaxBase, 10)
	if !ok {
		t.Fatal("invalid embedded PRVI maximum")
	}
	below := new(big.Int).Sub(max, big.NewInt(1))
	address := authtypes.NewModuleAddress("genesisfixture")
	initial := sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(below)))
	h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
		Params: banktypes.DefaultParams(),
		Balances: []banktypes.Balance{{Address: address.String(), Coins: initial}},
		Supply: initial,
	})
	if err := h.cap.InitGenesis(h.ctx, below.String(), h.bank); err != nil {
		t.Fatalf("one-aprvi-below-cap genesis rejected: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("valid below-cap genesis did not reconcile: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max))); err != nil {
		t.Fatalf("could not arrange untracked boundary unit: %v", err)
	}
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != below.String() {
		t.Fatalf("test precondition: declared supply unexpectedly changed: %s", got)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
		t.Fatalf("untracked unit reaching cap escaped conservation check: %v", err)
	}
	state, err := h.cap.Snapshot(h.ctx)
	if err != nil || state.GenesisBase != below.String() || state.LifetimeIssuedBase != below.String() {
		t.Fatalf("failed reconciliation changed immutable issuance: %+v, %v", state, err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
		t.Fatalf("native mint not forbidden after mismatch: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(below))); err != nil {
		t.Fatalf("could not restore original bank balance: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("restored valid below-cap balance failed reconciliation: %v", err)
	}
}
