// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title PriviDevCounter
 * @notice Non-financial EVM state-write compatibility fixture.
 *         No PRIV or PRVI token, no administrator, no real asset, no mainnet.
 */
contract PriviDevCounter {
    uint256 public count;

    event Incremented(address indexed caller, uint256 newValue);

    function increment() external {
        count += 1;
        emit Incremented(msg.sender, count);
    }
}
