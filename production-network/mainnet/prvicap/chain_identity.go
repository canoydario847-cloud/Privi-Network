package prvicap

import "fmt"

// ValidateEVMChainID rejects common upstream developer and public Ethereum
// chain identities for this Privi-specific application binary, before any
// bank or VM keeper is constructed. This does not register or independently
// verify a globally unique EIP-155 identity; that remains a launch gate.
//
// The caller must supply the approved chain ID via node configuration. Never
// take a numeric EVM identity from untrusted genesis metadata or default CLI
// flags. Financial production still requires signed genesis and release
// hashes, as well as a chain-id registry collision review.
func ValidateEVMChainID(id uint64) error {
    switch id {
    case 0, 1, 56, 97, 1337, 31337, 4221, 262144:
        return fmt.Errorf("Privi EVM chain ID %d is unset, upstream developer identity or reserved public chain; explicit reviewed EIP-155 ID required", id)
    default:
        return nil
    }
}
