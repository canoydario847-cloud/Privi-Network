// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {JoseToken} from "../src/JoseToken.sol";
import {JosePayments} from "../src/JosePayments.sol";

contract JoseTest is Test {
    JoseToken token;
    JosePayments pay;

    address treasury = makeAddr("treasury");
    address owner = makeAddr("owner");
    address alice = makeAddr("alice");
    address seller = makeAddr("seller");

    uint256 constant SUPPLY = 5_000_000_000;
    uint256 constant PRICE = 0.5 ether; // 0.5 JOSE per credit
    uint16 constant FEE = 250; // 2.5%

    function setUp() public {
        token = new JoseToken(SUPPLY, treasury);
        pay = new JosePayments(IERC20(address(token)), treasury, owner, PRICE, FEE);
        vm.prank(treasury);
        token.transfer(alice, 10_000 ether);
    }

    // ------------------------------------------------------------- token

    function test_TokenMetadataAndFixedSupply() public view {
        assertEq(token.name(), "Jose Coin");
        assertEq(token.symbol(), "JOSE");
        assertEq(token.decimals(), 18);
        assertEq(token.totalSupply(), SUPPLY * 1e18);
        assertEq(token.balanceOf(treasury) + token.balanceOf(alice), SUPPLY * 1e18);
    }

    function test_TokenRejectsZeroInputs() public {
        vm.expectRevert(JoseToken.ZeroRecipient.selector);
        new JoseToken(SUPPLY, address(0));
        vm.expectRevert(JoseToken.ZeroSupply.selector);
        new JoseToken(0, treasury);
    }

    function testFuzz_TransfersNeverChangeSupply(uint256 amount) public {
        amount = bound(amount, 0, token.balanceOf(alice));
        vm.prank(alice);
        token.transfer(seller, amount);
        assertEq(token.totalSupply(), SUPPLY * 1e18);
    }

    // ------------------------------------------------------------- credits

    function test_BuyCredits() public {
        bytes32 acct = keccak256("user-42");
        vm.startPrank(alice);
        token.approve(address(pay), 50 ether);
        vm.expectEmit(address(pay));
        emit JosePayments.CreditsPurchased(acct, alice, 100, 50 ether, PRICE);
        pay.buyCredits(acct, 100, 50 ether);
        vm.stopPrank();

        assertEq(token.balanceOf(address(pay)), 0, "contract holds nothing");
        assertEq(token.balanceOf(alice), 10_000 ether - 50 ether);
    }

    function test_BuyCreditsRespectsMaxCost() public {
        vm.prank(owner);
        pay.setPricePerCredit(1 ether);
        vm.startPrank(alice);
        token.approve(address(pay), type(uint256).max);
        vm.expectRevert(abi.encodeWithSelector(JosePayments.CostAboveMax.selector, 100 ether, 50 ether));
        pay.buyCredits(keccak256("a"), 100, 50 ether);
        vm.stopPrank();
    }

    function test_BuyCreditsRequiresApproval() public {
        vm.prank(alice);
        vm.expectRevert();
        pay.buyCredits(keccak256("a"), 1, PRICE);
    }

    function test_BuyCreditsZeroAndUnsetPrice() public {
        vm.prank(alice);
        vm.expectRevert(JosePayments.ZeroAmount.selector);
        pay.buyCredits(keccak256("a"), 0, 0);

        vm.prank(owner);
        pay.setPricePerCredit(0);
        vm.prank(alice);
        vm.expectRevert(JosePayments.PriceNotSet.selector);
        pay.buyCredits(keccak256("a"), 1, 1 ether);
    }

    // ------------------------------------------------------------- market

    function test_PayOrderSplitsFee() public {
        bytes32 order = keccak256("order-1");
        uint256 treasuryBefore = token.balanceOf(treasury);
        vm.startPrank(alice);
        token.approve(address(pay), 200 ether);
        pay.payOrder(order, seller, 200 ether);
        vm.stopPrank();

        assertEq(token.balanceOf(seller), 195 ether);
        assertEq(token.balanceOf(treasury) - treasuryBefore, 5 ether);
        assertTrue(pay.orderPaid(order));
    }

    function test_PayOrderCannotBePaidTwice() public {
        bytes32 order = keccak256("order-1");
        vm.startPrank(alice);
        token.approve(address(pay), 400 ether);
        pay.payOrder(order, seller, 200 ether);
        vm.expectRevert(abi.encodeWithSelector(JosePayments.OrderAlreadyPaid.selector, order));
        pay.payOrder(order, seller, 200 ether);
        vm.stopPrank();
    }

    function test_PayOrderRejectsBadInput() public {
        vm.startPrank(alice);
        token.approve(address(pay), 100 ether);
        vm.expectRevert(JosePayments.ZeroAddress.selector);
        pay.payOrder(keccak256("o"), address(0), 1 ether);
        vm.expectRevert(JosePayments.SellerIsBuyer.selector);
        pay.payOrder(keccak256("o"), alice, 1 ether);
        vm.expectRevert(JosePayments.ZeroAmount.selector);
        pay.payOrder(keccak256("o"), seller, 0);
        vm.stopPrank();
    }

    function testFuzz_PayOrderConservesValue(uint256 amount, uint16 feeBps) public {
        amount = bound(amount, 1, token.balanceOf(alice));
        feeBps = uint16(bound(feeBps, 0, pay.MAX_FEE_BPS()));
        vm.prank(owner);
        pay.setMarketFeeBps(feeBps);

        uint256 tBefore = token.balanceOf(treasury);
        vm.startPrank(alice);
        token.approve(address(pay), amount);
        pay.payOrder(keccak256(abi.encode(amount, feeBps)), seller, amount);
        vm.stopPrank();

        assertEq(token.balanceOf(seller) + (token.balanceOf(treasury) - tBefore), amount);
        assertEq(token.balanceOf(address(pay)), 0);
    }

    // ------------------------------------------------------------- admin

    function test_OnlyOwnerAdmin() public {
        vm.startPrank(alice);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, alice));
        pay.setPricePerCredit(1);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, alice));
        pay.setTreasury(alice);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, alice));
        pay.setMarketFeeBps(1);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, alice));
        pay.pause();
        vm.stopPrank();
    }

    function test_FeeCapAndRenounceDisabled() public {
        vm.startPrank(owner);
        vm.expectRevert(JosePayments.FeeTooHigh.selector);
        pay.setMarketFeeBps(1_001);
        vm.expectRevert(bytes("renounce disabled"));
        pay.renounceOwnership();
        vm.stopPrank();
    }

    function test_PauseBlocksPayments() public {
        vm.prank(owner);
        pay.pause();
        vm.startPrank(alice);
        token.approve(address(pay), 10 ether);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        pay.buyCredits(keccak256("a"), 1, PRICE);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        pay.payOrder(keccak256("o"), seller, 1 ether);
        vm.stopPrank();
    }

    function test_TwoStepOwnershipTransfer() public {
        vm.prank(owner);
        pay.transferOwnership(alice);
        assertEq(pay.owner(), owner);
        vm.prank(alice);
        pay.acceptOwnership();
        assertEq(pay.owner(), alice);
    }

    function test_RescueSendsStrayTokensToTreasury() public {
        vm.prank(alice);
        token.transfer(address(pay), 7 ether);
        uint256 before = token.balanceOf(treasury);
        vm.prank(owner);
        pay.rescue(IERC20(address(token)));
        assertEq(token.balanceOf(treasury) - before, 7 ether);
    }
}
