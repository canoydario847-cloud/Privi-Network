// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @title Jose Coin (JOSE)
/// @notice Fixed-supply ERC-20 on Base. The whole supply is created once at
///         deployment and sent to `recipient`. There is no owner, no minting,
///         no pausing, no blacklist and no upgrade path: nobody, including the
///         deployer, can create more JOSE or move anyone else's JOSE.
contract JoseToken is ERC20 {
    error ZeroRecipient();
    error ZeroSupply();

    /// @param initialSupply Whole-token amount (e.g. 1_000_000_000 for one billion). 18 decimals are added here.
    /// @param recipient Wallet that receives the entire supply (e.g. the Privi treasury multisig).
    constructor(uint256 initialSupply, address recipient) ERC20("Jose Coin", "JOSE") {
        if (recipient == address(0)) revert ZeroRecipient();
        if (initialSupply == 0) revert ZeroSupply();
        _mint(recipient, initialSupply * 10 ** decimals());
    }
}
