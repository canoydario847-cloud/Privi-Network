// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {JoseToken} from "../src/JoseToken.sol";
import {JosePayments} from "../src/JosePayments.sol";

/// @notice Deploys JOSE and JosePayments. Every value comes from the environment:
///   JOSE_SUPPLY         whole tokens, e.g. 1000000000 (required, no default on purpose)
///   JOSE_TREASURY       wallet that receives the full supply and all payments (required)
///   JOSE_OWNER          admin of JosePayments (defaults to JOSE_TREASURY)
///   JOSE_CREDIT_PRICE   JOSE base units per AI credit, e.g. 500000000000000000 for 0.5 JOSE (default 0 = credits off)
///   JOSE_MARKET_FEE_BPS market fee, 250 = 2.5% (default 250, max 1000)
/// Run with your own wallet, e.g. `--ledger` or `--account <keystore>`. Never put a private key in a file.
contract Deploy is Script {
    function run() external {
        uint256 supply = vm.envUint("JOSE_SUPPLY");
        address treasury = vm.envAddress("JOSE_TREASURY");
        address owner = vm.envOr("JOSE_OWNER", treasury);
        uint256 price = vm.envOr("JOSE_CREDIT_PRICE", uint256(0));
        uint16 feeBps = uint16(vm.envOr("JOSE_MARKET_FEE_BPS", uint256(250)));

        vm.startBroadcast();
        JoseToken token = new JoseToken(supply, treasury);
        JosePayments payments = new JosePayments(IERC20(address(token)), treasury, owner, price, feeBps);
        vm.stopBroadcast();

        console.log("Chain id        ", block.chainid);
        console.log("JOSE token      ", address(token));
        console.log("JosePayments    ", address(payments));
        console.log("Treasury        ", treasury);
        console.log("Payments owner  ", owner);
    }
}
