// Package capmodel tests the proposed PRVI 1-billion lifetime issuance rule.
//
// SAFETY: This is a pure-Go OFF-CHAIN reference model, NOT a Cosmos SDK keeper,
// not consensus logic, and not wired into a live blockchain. Passing its unit
// tests does not constrain any deployed chain or authorize real PRVI minting.
package capmodel

import (
    "errors"
    "math/big"
    "sync"
)

const (
    Symbol      = "PRVI"
    BaseDenom   = "aprvi"       // provisional, requires review
    Decimals    = 18            // provisional, requires review
    MaximumPRVI = "1000000000"
    MaximumBase = "1000000000000000000000000000" // 10^27 base units
)

var (
    ErrInvalidAmount       = errors.New("amount must be a canonical positive ASCII decimal integer")
    ErrInvalidGenesis      = errors.New("genesis issuance must be positive and at or below 1B PRVI cap")
    ErrLifetimeCapExceeded = errors.New("PRVI lifetime issuance would exceed the maximum")
    ErrInsufficientSupply  = errors.New("burn would exceed current outstanding supply")
)

// Snapshot is a copy-only view of the model accounting. No external caller
// can mutate the ledger by modifying returned values.
type Snapshot struct {
    GenesisBase     string `json:"genesis_base"`
    LifetimeIssued  string `json:"lifetime_issued_base"`
    Outstanding     string `json:"outstanding_base"`
    Burned          string `json:"burned_base"`
    RemainingToMint string `json:"remaining_lifetime_to_mint_base"`
    Maximum         string `json:"maximum_base"`
}

// Ledger is a concurrent in-memory reference state machine. It deliberately
// does not persist balances, authorize minters, interact with banks, or perform
// chain state transitions. Those production requirements remain BLOCKED.
type Ledger struct {
    mu sync.Mutex
    genesis *big.Int
    lifetime *big.Int
    outstanding *big.Int
    burned *big.Int
}

func maxBase() *big.Int {
    v, ok := new(big.Int).SetString(MaximumBase, 10)
    if !ok { panic("invalid compiled-in maximum PRVI constant") }
    return v
}

func parsePositiveASCII(raw string) (*big.Int, error) {
    if raw == "" || raw[0] == '0' {
        return nil, ErrInvalidAmount
    }
    for _, b := range []byte(raw) {
        if b < '0' || b > '9' { return nil, ErrInvalidAmount }
    }
    v, ok := new(big.Int).SetString(raw, 10)
    if !ok || v.Sign() <= 0 { return nil, ErrInvalidAmount }
    return v, nil
}

// New initializes issuance from a separately reconciled genesis PRVI amount.
// It does NOT validate operator signatures, bank module accounts, denomination,
// vesting or any real blockchain genesis file.
func New(genesisAmountBase string) (*Ledger, error) {
    amount, err := parsePositiveASCII(genesisAmountBase)
    if err != nil { return nil, ErrInvalidGenesis }
    if amount.Cmp(maxBase()) > 0 { return nil, ErrInvalidGenesis }
    return &Ledger{
        genesis: new(big.Int).Set(amount),
        lifetime: new(big.Int).Set(amount),
        outstanding: new(big.Int).Set(amount),
        burned: new(big.Int),
    }, nil
}

func (l *Ledger) snapshotLocked() Snapshot {
    return Snapshot{
        GenesisBase: l.genesis.String(),
        LifetimeIssued: l.lifetime.String(),
        Outstanding: l.outstanding.String(),
        Burned: l.burned.String(),
        RemainingToMint: new(big.Int).Sub(maxBase(), l.lifetime).String(),
        Maximum: MaximumBase,
    }
}

func (l *Ledger) Snapshot() Snapshot {
    l.mu.Lock()
    defer l.mu.Unlock()
    return l.snapshotLocked()
}

// Mint simulates a NEW issuance operation. It rejects the entire operation
// before changing state if cumulative ever-issued PRVI would exceed the cap.
// A real app must run equivalent checks atomically within the SAME consensus
// state transition as bank.MintCoins for EVERY possible mint authority.
func (l *Ledger) Mint(amountBase string) (Snapshot, error) {
    amount, err := parsePositiveASCII(amountBase)
    if err != nil { return Snapshot{}, err }
    l.mu.Lock()
    defer l.mu.Unlock()
    nextLifetime := new(big.Int).Add(l.lifetime, amount)
    if nextLifetime.Cmp(maxBase()) > 0 {
        return Snapshot{}, ErrLifetimeCapExceeded
    }
    l.lifetime = nextLifetime
    l.outstanding.Add(l.outstanding, amount)
    return l.snapshotLocked(), nil
}

// Burn removes supply but NEVER decreases cumulative issuance or increases the
// number of PRVI that may be minted. This prevents burn-and-remint cap bypasses.
func (l *Ledger) Burn(amountBase string) (Snapshot, error) {
    amount, err := parsePositiveASCII(amountBase)
    if err != nil { return Snapshot{}, err }
    l.mu.Lock()
    defer l.mu.Unlock()
    if amount.Cmp(l.outstanding) > 0 {
        return Snapshot{}, ErrInsufficientSupply
    }
    l.outstanding.Sub(l.outstanding, amount)
    l.burned.Add(l.burned, amount)
    return l.snapshotLocked(), nil
}

// Vesting release, staking delegation, bank sends and distribution transfers
// must move pre-issued units, not call Mint. This model intentionally has no
// mint function for these actions.
