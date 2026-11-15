package prvicap

import (
    "errors"
    "strings"
    "testing"
)

func TestCapStateRejectsOversizedConsensusAmounts(t *testing.T) {
    oversized := strings.Repeat("9", 100000)
    if err := ValidateGenesisBase(oversized); !errors.Is(err, ErrInvalidGenesis) {
        t.Fatalf("oversized genesis must fail before numeric parsing: %v", err)
    }
    k, data, ctx := setup(t, whole(1))
    data.content[string(keyGenesis)] = []byte(oversized)
    if _, err := k.Snapshot(ctx); !errors.Is(err, ErrStoreCorrupt) {
        t.Fatalf("oversized persisted consensus record must fail closed: %v", err)
    }
}

func TestCapStateCanonicalMaximumAndLeadingZero(t *testing.T) {
    if err := ValidateGenesisBase(MaxBase); err != nil {
        t.Fatalf("exact cap must be valid: %v", err)
    }
    if err := ValidateGenesisBase("0" + MaxBase); !errors.Is(err, ErrInvalidGenesis) {
        t.Fatalf("leading-zero cap must be invalid: %v", err)
    }
}
