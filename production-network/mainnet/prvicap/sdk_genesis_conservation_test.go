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


// A conservation check must not confuse an ordinary balance redistribution
// with new native issuance. This fixture uses the SDK's unchecked setter only
// to model two matching account writes; it does NOT validate transfer
// authorization or permit unchecked setters in a production Privi app.
func TestActualSDKBankConservingRedistributionAndOneUnitDrift(t *testing.T) {
	h := newRealBankHarness(t)
	h.genesisFund(t, 100)
	source := authtypes.NewModuleAddress("genesisfixture")
	recipient := authtypes.NewModuleAddress("genesisrecipient")

	// Simulate a 40-aprvi transfer: both account balances change, but
	// the bank's declared supply remains 100 and the actual sum is 100.
	if err := h.bank.UncheckedSetBalance(h.ctx, source, sdk.NewInt64Coin(BaseDenom, 60)); err != nil {
		t.Fatalf("could not adjust source balance: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, recipient, sdk.NewInt64Coin(BaseDenom, 40)); err != nil {
		t.Fatalf("could not adjust recipient balance: %v", err)
	}
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != "100" {
		t.Fatalf("fixture unexpectedly changed declared bank supply: %s", got)
	}
	if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil {
		t.Fatalf("conserving two-account genesis was rejected: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("conserving redistribution failed reconciliation: %v", err)
	}

	// An extra aprvi in one account without a matching debit must be
	// rejected even though the declared supply counter stays at 100.
	if err := h.bank.UncheckedSetBalance(h.ctx, recipient, sdk.NewInt64Coin(BaseDenom, 41)); err != nil {
		t.Fatalf("could not arrange one-unit drift: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
		t.Fatalf("one-unit drift escaped native conservation: %v", err)
	}
	if state, err := h.cap.Snapshot(h.ctx); err != nil ||
		state.GenesisBase != "100" || state.LifetimeIssuedBase != "100" {
		t.Fatalf("drift changed immutable issuance: %+v, %v", state, err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
		t.Fatalf("native mint was allowed after drift: %v", err)
	}

	if err := h.bank.UncheckedSetBalance(h.ctx, recipient, sdk.NewInt64Coin(BaseDenom, 40)); err != nil {
		t.Fatalf("could not restore recipient balance: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("restored conserving balances failed reconciliation: %v", err)
	}
}


// A native-only supply guard must reconcile aprvi even when x/bank contains
// unrelated denominations. The unrelated balance is not PRVI issuance.
func TestActualSDKBankMultiDenomNativeConservation(t *testing.T) {
	h := newRealBankHarness(t)
	address := authtypes.NewModuleAddress("genesisfixture")
	initial := sdk.NewCoins(
		sdk.NewInt64Coin(BaseDenom, 100),
		sdk.NewInt64Coin("uother", 50),
	)
	h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
		Params:   banktypes.DefaultParams(),
		Balances: []banktypes.Balance{{Address: address.String(), Coins: initial}},
		Supply:   initial,
	})
	if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil {
		t.Fatalf("multi-denom native genesis rejected: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("unrelated denom counted as native supply: %v", err)
	}
	// A change confined to an unrelated denomination must not be mistaken
	// for native issuance. The SDK's unchecked setter is a test fixture only.
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin("uother", 51)); err != nil {
		t.Fatalf("could not arrange unrelated-denom balance change: %v", err)
	}
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != "100" {
		t.Fatalf("unrelated-denom change altered declared native supply: %s", got)
	}
	if got := h.bank.GetSupply(h.ctx, "uother").Amount.String(); got != "50" {
		t.Fatalf("test precondition: unrelated declared supply changed: %s", got)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("unrelated-denom-only drift incorrectly rejected native supply: %v", err)
	}
	if state, err := h.cap.Snapshot(h.ctx); err != nil ||
		state.GenesisBase != "100" || state.LifetimeIssuedBase != "100" {
		t.Fatalf("unrelated-denom change altered native issuance record: %+v, %v", state, err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin("uother", 50)); err != nil {
		t.Fatalf("could not restore unrelated-denom balance: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin(BaseDenom, 101)); err != nil {
		t.Fatalf("could not arrange native-only drift: %v", err)
	}
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != "100" {
		t.Fatalf("test precondition: native declared supply changed to %s", got)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
		t.Fatalf("native drift concealed by unrelated denomination: %v", err)
	}
	if state, err := h.cap.Snapshot(h.ctx); err != nil ||
		state.GenesisBase != "100" || state.LifetimeIssuedBase != "100" {
		t.Fatalf("failed reconciliation changed issuance record: %+v, %v", state, err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
		t.Fatalf("native mint allowed after multi-denom mismatch: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin(BaseDenom, 100)); err != nil {
		t.Fatalf("could not restore native balance: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("restored multi-denom native balance rejected: %v", err)
	}
}

// TestActualSDKBankCrossDenomOffsetCannotHideNativeDeficit ensures a native shortfall cannot be
// disguised by adding the same number of units of an unrelated denomination.
// Total coin counts are not a substitute for per-denomination conservation.
func TestActualSDKBankCrossDenomOffsetCannotHideNativeDeficit(t *testing.T) {
	h := newRealBankHarness(t)
	address := authtypes.NewModuleAddress("genesisfixture")
	initial := sdk.NewCoins(
		sdk.NewInt64Coin(BaseDenom, 100),
		sdk.NewInt64Coin("uother", 50),
	)
	h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
		Params:   banktypes.DefaultParams(),
		Balances: []banktypes.Balance{{Address: address.String(), Coins: initial}},
		Supply:   initial,
	})
	if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil {
		t.Fatalf("valid mixed-denomination genesis rejected: %v", err)
	}
	// UncheckedSetBalance is a test-only corruption fixture, not a
	// permitted production balance update.
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin(BaseDenom, 99)); err != nil {
		t.Fatalf("could not arrange native shortfall: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin("uother", 51)); err != nil {
		t.Fatalf("could not arrange offsetting unrelated units: %v", err)
	}
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != "100" {
		t.Fatalf("native supply precondition changed: %s", got)
	}
	if got := h.bank.GetSupply(h.ctx, "uother").Amount.String(); got != "50" {
		t.Fatalf("unrelated supply precondition changed: %s", got)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
		t.Fatalf("offsetting unrelated units concealed native deficit: %v", err)
	}
	if state, err := h.cap.Snapshot(h.ctx); err != nil ||
		state.GenesisBase != "100" || state.LifetimeIssuedBase != "100" {
		t.Fatalf("failed reconciliation changed issuance: %+v, %v", state, err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
		t.Fatalf("native mint allowed after native deficit: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin(BaseDenom, 100)); err != nil {
		t.Fatalf("could not restore native balance: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin("uother", 50)); err != nil {
		t.Fatalf("could not restore unrelated balance: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("restored native balances rejected: %v", err)
	}
}
// An offsetting unrelated-denomination deficit cannot disguise a native
// aprvi surplus during genesis, even if x/bank's declared supply is unchanged.
// A rejected candidate must leave the cap uninitialized and native mint
// unavailable; restoring honest balances permits one initialization.
func TestActualSDKBankGenesisRejectsCrossDenomOffset(t *testing.T) {
	h := newRealBankHarness(t)
	address := authtypes.NewModuleAddress("genesisfixture")
	initial := sdk.NewCoins(
		sdk.NewInt64Coin(BaseDenom, 100),
		sdk.NewInt64Coin("uother", 50),
	)
	h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
		Params:   banktypes.DefaultParams(),
		Balances: []banktypes.Balance{{Address: address.String(), Coins: initial}},
		Supply:   initial,
	})
	// These unchecked writes simulate a corrupted candidate genesis; they
	// are not authorized application balance operations.
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin(BaseDenom, 101)); err != nil {
		t.Fatalf("could not arrange untracked native surplus: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin("uother", 49)); err != nil {
		t.Fatalf("could not arrange offsetting unrelated deficit: %v", err)
	}
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != "100" {
		t.Fatalf("native declared supply unexpectedly changed: %s", got)
	}
	if got := h.bank.GetSupply(h.ctx, "uother").Amount.String(); got != "50" {
		t.Fatalf("unrelated declared supply unexpectedly changed: %s", got)
	}
	if err := h.cap.InitGenesis(h.ctx, "100", h.bank); !errors.Is(err, ErrBankSupplyMismatch) {
		t.Fatalf("offsetting unrelated deficit concealed native genesis surplus: %v", err)
	}
	if _, err := h.cap.Snapshot(h.ctx); !errors.Is(err, ErrNotInitialized) {
		t.Fatalf("rejected mixed-denomination genesis persisted issuance: %v", err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrNotInitialized) {
		t.Fatalf("rejected genesis permitted native mint: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin(BaseDenom, 100)); err != nil {
		t.Fatalf("could not restore native balance: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, address, sdk.NewInt64Coin("uother", 50)); err != nil {
		t.Fatalf("could not restore unrelated balance: %v", err)
	}
	if err := h.cap.InitGenesis(h.ctx, "100", h.bank); err != nil {
		t.Fatalf("restored mixed-denomination genesis rejected: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("restored mixed-denomination genesis failed reconciliation: %v", err)
	}
	if state, err := h.cap.Snapshot(h.ctx); err != nil ||
		state.GenesisBase != "100" || state.LifetimeIssuedBase != "100" {
		t.Fatalf("restored genesis issuance record invalid: %+v, %v", state, err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
		t.Fatalf("restored genesis permitted native mint: %v", err)
	}
}

// TestActualSDKBankGenesisRejectsDistributedHiddenOverCap exercises the
// pre-initialization boundary when declared bank supply is exactly the
// 1B-PRVI cap but an unchecked write adds one aprvi to a second account.
// This is a corruption fixture, not an authorized transfer or mint path.
func TestActualSDKBankGenesisRejectsDistributedHiddenOverCap(t *testing.T) {
	h := newRealBankHarness(t)
	max, ok := new(big.Int).SetString(MaxBase, 10)
	if !ok {
		t.Fatal("invalid embedded PRVI maximum")
	}
	remaining := new(big.Int).Sub(max, big.NewInt(1))
	firstAddr := authtypes.NewModuleAddress("genesisfixtureone")
	secondAddr := authtypes.NewModuleAddress("genesisfixturetwo")
	first := sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))
	second := sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(remaining)))
	supply := sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max)))
	h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
		Params: banktypes.DefaultParams(),
		Balances: []banktypes.Balance{
			{Address: firstAddr.String(), Coins: first},
			{Address: secondAddr.String(), Coins: second},
		},
		Supply: supply,
	})
	// The second account now contains the entire cap in addition to
	// the first account's one aprvi; x/bank still declares only the cap.
	if err := h.bank.UncheckedSetBalance(h.ctx, secondAddr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max))); err != nil {
		t.Fatalf("could not arrange hidden distributed over-cap unit: %v", err)
	}
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != MaxBase {
		t.Fatalf("test precondition: declared bank supply changed to %s", got)
	}
	if got := h.bank.GetBalance(h.ctx, secondAddr, BaseDenom).Amount.BigInt(); got.Cmp(max) != 0 {
		t.Fatalf("test precondition: second account balance is %s", got)
	}
	if err := h.cap.InitGenesis(h.ctx, MaxBase, h.bank); !errors.Is(err, ErrBankSupplyMismatch) {
		t.Fatalf("distributed hidden over-cap balance initialized issuance: %v", err)
	}
	if _, err := h.cap.Snapshot(h.ctx); !errors.Is(err, ErrNotInitialized) {
		t.Fatalf("rejected distributed genesis persisted issuance: %v", err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrNotInitialized) {
		t.Fatalf("native mint did not fail closed after rejected genesis: %v", err)
	}

	// Correcting the single corrupted balance must allow exactly-cap
	// initialization, with immutable issuance and mint prohibition.
	if err := h.bank.UncheckedSetBalance(h.ctx, secondAddr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(remaining))); err != nil {
		t.Fatalf("could not restore second account: %v", err)
	}
	if err := h.cap.InitGenesis(h.ctx, MaxBase, h.bank); err != nil {
		t.Fatalf("restored exact-cap genesis rejected: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("restored distributed cap failed reconciliation: %v", err)
	}
	if state, err := h.cap.Snapshot(h.ctx); err != nil || state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
		t.Fatalf("restored distributed issuance invalid: %+v, %v", state, err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
		t.Fatalf("native mint allowed after restored initialization: %v", err)
	}
}


// TestActualSDKBankGenesisConservingRedistributionAtCap verifies that a
// balance-preserving redistribution at the exact 1B-PRVI boundary is not
// mistaken for new issuance. The unchecked setter is used only to construct
// the disposable SDK fixture, not as an authorized production transfer.
func TestActualSDKBankGenesisConservingRedistributionAtCap(t *testing.T) {
	h := newRealBankHarness(t)
	max, ok := new(big.Int).SetString(MaxBase, 10)
	if !ok {
		t.Fatal("invalid embedded PRVI maximum")
	}
	remaining := new(big.Int).Sub(max, big.NewInt(1))
	firstAddr := authtypes.NewModuleAddress("redistributionone")
	secondAddr := authtypes.NewModuleAddress("redistributiontwo")
	supply := sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max)))
	h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
		Params: banktypes.DefaultParams(),
		Balances: []banktypes.Balance{
			{Address: firstAddr.String(), Coins: sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))},
			{Address: secondAddr.String(), Coins: sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(remaining)))},
		},
		Supply: supply,
	})
	// Move the first account's last aprvi to the second account. The
	// declared bank supply and the sum of actual balances both stay at cap.
	if err := h.bank.UncheckedSetBalance(h.ctx, firstAddr, sdk.NewInt64Coin(BaseDenom, 0)); err != nil {
		t.Fatalf("could not empty first fixture account: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, secondAddr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max))); err != nil {
		t.Fatalf("could not credit second fixture account: %v", err)
	}
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != MaxBase {
		t.Fatalf("declared native supply changed: %s", got)
	}
	if got := h.bank.GetBalance(h.ctx, firstAddr, BaseDenom).Amount.String(); got != "0" {
		t.Fatalf("first account was not emptied: %s", got)
	}
	if got := h.bank.GetBalance(h.ctx, secondAddr, BaseDenom).Amount.String(); got != MaxBase {
		t.Fatalf("second account does not hold the exact cap: %s", got)
	}
	if err := h.cap.InitGenesis(h.ctx, MaxBase, h.bank); err != nil {
		t.Fatalf("conserving redistribution rejected at exact cap: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("conserving redistribution failed reconciliation: %v", err)
	}
	if state, err := h.cap.Snapshot(h.ctx); err != nil ||
		state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
		t.Fatalf("conserving redistribution changed issuance record: %+v, %v", state, err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
		t.Fatalf("conserving redistribution permitted native mint: %v", err)
	}
}


// TestActualSDKBankPostGenesisConservingRedistributionAtCap checks that
// reconciliation accepts a zero-sum account movement after cap initialization.
// UncheckedSetBalance is only a disposable corruption/transfer fixture.
func TestActualSDKBankPostGenesisConservingRedistributionAtCap(t *testing.T) {
	h := newRealBankHarness(t)
	max, ok := new(big.Int).SetString(MaxBase, 10)
	if !ok {
		t.Fatal("invalid embedded PRVI maximum")
	}
	remaining := new(big.Int).Sub(max, big.NewInt(1))
	firstAddr := authtypes.NewModuleAddress("postgenesisone")
	secondAddr := authtypes.NewModuleAddress("postgenesistwo")
	h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
		Params: banktypes.DefaultParams(),
		Balances: []banktypes.Balance{
			{Address: firstAddr.String(), Coins: sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))},
			{Address: secondAddr.String(), Coins: sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(remaining)))},
		},
		Supply: sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max))),
	})
	if err := h.cap.InitGenesis(h.ctx, MaxBase, h.bank); err != nil {
		t.Fatalf("exact-cap genesis rejected: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, firstAddr, sdk.NewInt64Coin(BaseDenom, 0)); err != nil {
		t.Fatalf("could not debit first account: %v", err)
	}
	if err := h.bank.UncheckedSetBalance(h.ctx, secondAddr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max))); err != nil {
		t.Fatalf("could not credit second account: %v", err)
	}
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != MaxBase {
		t.Fatalf("declared native supply changed: %s", got)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("post-genesis conserving movement rejected: %v", err)
	}
	if state, err := h.cap.Snapshot(h.ctx); err != nil ||
		state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
		t.Fatalf("post-genesis redistribution altered issuance: %+v, %v", state, err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
		t.Fatalf("native mint allowed after post-genesis redistribution: %v", err)
	}
}


// TestActualSDKBankPostGenesisPartialRedistributionFailsClosed ensures that
// reconciliation cannot accept a half-applied transfer at the native cap.
// The unchecked setters are exclusively disposable SDK test fixtures.
func TestActualSDKBankPostGenesisPartialRedistributionFailsClosed(t *testing.T) {
	h := newRealBankHarness(t)
	max, ok := new(big.Int).SetString(MaxBase, 10)
	if !ok {
		t.Fatal("invalid embedded PRVI maximum")
	}
	remaining := new(big.Int).Sub(max, big.NewInt(1))
	firstAddr := authtypes.NewModuleAddress("partialtransferone")
	secondAddr := authtypes.NewModuleAddress("partialtransfertwo")
	h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
		Params: banktypes.DefaultParams(),
		Balances: []banktypes.Balance{
			{Address: firstAddr.String(), Coins: sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))},
			{Address: secondAddr.String(), Coins: sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(remaining)))},
		},
		Supply: sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max))),
	})
	if err := h.cap.InitGenesis(h.ctx, MaxBase, h.bank); err != nil {
		t.Fatalf("exact-cap genesis rejected: %v", err)
	}
	// Only the debit has happened: actual supply is one aprvi below cap.
	if err := h.bank.UncheckedSetBalance(h.ctx, firstAddr, sdk.NewInt64Coin(BaseDenom, 0)); err != nil {
		t.Fatalf("could not construct partial debit: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
		t.Fatalf("partial transfer incorrectly reconciled: %v", err)
	}
	if state, err := h.cap.Snapshot(h.ctx); err != nil ||
		state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
		t.Fatalf("failed reconciliation altered issuance: %+v, %v", state, err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
		t.Fatalf("native mint allowed after partial debit: %v", err)
	}
	// Completing the matching credit restores conservation without issuance.
	if err := h.bank.UncheckedSetBalance(h.ctx, secondAddr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max))); err != nil {
		t.Fatalf("could not complete matching credit: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("completed conserving transfer rejected: %v", err)
	}
}


// TestActualSDKBankPostGenesisPartialCreditFailsClosed covers the opposite
// half-transfer ordering: crediting the recipient before debiting the sender.
// UncheckedSetBalance is used only in this disposable SDK corruption fixture.
func TestActualSDKBankPostGenesisPartialCreditFailsClosed(t *testing.T) {
	h := newRealBankHarness(t)
	max, ok := new(big.Int).SetString(MaxBase, 10)
	if !ok {
		t.Fatal("invalid embedded PRVI maximum")
	}
	remaining := new(big.Int).Sub(max, big.NewInt(1))
	firstAddr := authtypes.NewModuleAddress("partialcreditone")
	secondAddr := authtypes.NewModuleAddress("partialcredittwo")
	h.bank.InitGenesis(h.ctx, &banktypes.GenesisState{
		Params: banktypes.DefaultParams(),
		Balances: []banktypes.Balance{
			{Address: firstAddr.String(), Coins: sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))},
			{Address: secondAddr.String(), Coins: sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(remaining)))},
		},
		Supply: sdk.NewCoins(sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max))),
	})
	if err := h.cap.InitGenesis(h.ctx, MaxBase, h.bank); err != nil {
		t.Fatalf("exact-cap genesis rejected: %v", err)
	}
	// Only the credit has happened: actual native supply exceeds the cap.
	if err := h.bank.UncheckedSetBalance(h.ctx, secondAddr, sdk.NewCoin(BaseDenom, sdkmath.NewIntFromBigInt(max))); err != nil {
		t.Fatalf("could not construct partial credit: %v", err)
	}
	if got := h.bank.GetSupply(h.ctx, BaseDenom).Amount.String(); got != MaxBase {
		t.Fatalf("test precondition: declared supply changed: %s", got)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); !errors.Is(err, ErrUnexpectedSupply) {
		t.Fatalf("partial credit incorrectly reconciled: %v", err)
	}
	if state, err := h.cap.Snapshot(h.ctx); err != nil ||
		state.GenesisBase != MaxBase || state.LifetimeIssuedBase != MaxBase {
		t.Fatalf("failed reconciliation altered issuance: %+v, %v", state, err)
	}
	if err := h.cap.MintRestriction(h.ctx, sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1))); !errors.Is(err, ErrMintForbidden) {
		t.Fatalf("native mint allowed after partial credit: %v", err)
	}
	// Completing the debit restores the original cap without new issuance.
	if err := h.bank.UncheckedSetBalance(h.ctx, firstAddr, sdk.NewInt64Coin(BaseDenom, 0)); err != nil {
		t.Fatalf("could not complete matching debit: %v", err)
	}
	if err := h.cap.Reconcile(h.ctx, h.bank); err != nil {
		t.Fatalf("completed conserving transfer rejected: %v", err)
	}
}
