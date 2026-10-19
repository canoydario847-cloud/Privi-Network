package prvicap

import "testing"

func TestPriviEVMChainIdentityRejectsDeveloperAndPublicIDs(t *testing.T) {
    for _, id := range []uint64{0, 1, 56, 97, 1337, 31337, 4221, 262144} {
        if err := ValidateEVMChainID(id); err == nil {
            t.Fatalf("EVM chain ID %d should be blocked before app construction", id)
        }
    }
}

func TestPriviEVMChainIdentityAcceptsCandidateForFurtherReviewOnly(t *testing.T) {
    for _, id := range []uint64{424242, 999999, ^uint64(0)} {
        if err := ValidateEVMChainID(id); err != nil {
            t.Fatalf("EVM chain ID %d syntactically eligible for independent review: %v", id, err)
        }
    }
}
