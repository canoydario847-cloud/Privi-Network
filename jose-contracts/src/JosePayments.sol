// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable, Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title Jose payments: AI credits and Jose Market orders, paid in JOSE
/// @notice This contract never holds user funds. Every payment moves JOSE
///         straight from the payer to the treasury (credits) or to the seller
///         and treasury (market orders), and emits an event the Jose backend
///         reads to add credits or mark an order paid.
///
///         Payers first `approve` this contract on the JOSE token for at most
///         the amount they intend to spend.
contract JosePayments is Ownable2Step, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    /// @notice Maximum market fee: 10%.
    uint16 public constant MAX_FEE_BPS = 1_000;

    IERC20 public immutable jose;
    address public treasury;
    /// @notice Price of one AI credit, in JOSE base units (18 decimals).
    uint256 public pricePerCredit;
    /// @notice Jose Market fee in basis points (100 = 1%).
    uint16 public marketFeeBps;
    /// @notice Market order ids that have already been paid.
    mapping(bytes32 orderId => bool) public orderPaid;

    event CreditsPurchased(
        bytes32 indexed accountId, address indexed payer, uint256 credits, uint256 cost, uint256 pricePerCredit
    );
    event OrderPaid(
        bytes32 indexed orderId, address indexed buyer, address indexed seller, uint256 amount, uint256 fee
    );
    event PriceChanged(uint256 oldPrice, uint256 newPrice);
    event TreasuryChanged(address oldTreasury, address newTreasury);
    event MarketFeeChanged(uint16 oldFeeBps, uint16 newFeeBps);
    event Rescued(address indexed token, address indexed to, uint256 amount);

    error ZeroAddress();
    error ZeroAmount();
    error PriceNotSet();
    error CostAboveMax(uint256 cost, uint256 maxCost);
    error FeeTooHigh();
    error OrderAlreadyPaid(bytes32 orderId);
    error SellerIsBuyer();

    constructor(IERC20 jose_, address treasury_, address owner_, uint256 pricePerCredit_, uint16 marketFeeBps_)
        Ownable(owner_)
    {
        if (address(jose_) == address(0) || treasury_ == address(0)) revert ZeroAddress();
        if (marketFeeBps_ > MAX_FEE_BPS) revert FeeTooHigh();
        jose = jose_;
        treasury = treasury_;
        pricePerCredit = pricePerCredit_;
        marketFeeBps = marketFeeBps_;
        emit TreasuryChanged(address(0), treasury_);
        emit PriceChanged(0, pricePerCredit_);
        emit MarketFeeChanged(0, marketFeeBps_);
    }

    // ---------------------------------------------------------------- users

    /// @notice Buy Jose AI credits for a Jose account.
    /// @param accountId The Jose account (hash of the backend user id) that receives the credits.
    /// @param credits Number of credits to buy.
    /// @param maxCost Most JOSE the payer accepts to spend; protects against a price change mid-transaction.
    function buyCredits(bytes32 accountId, uint256 credits, uint256 maxCost) external whenNotPaused nonReentrant {
        if (credits == 0) revert ZeroAmount();
        uint256 price = pricePerCredit;
        if (price == 0) revert PriceNotSet();
        uint256 cost = credits * price;
        if (cost > maxCost) revert CostAboveMax(cost, maxCost);

        jose.safeTransferFrom(msg.sender, treasury, cost);
        emit CreditsPurchased(accountId, msg.sender, credits, cost, price);
    }

    /// @notice Pay a Jose Market order. The seller receives `amount` minus the market fee.
    /// @param orderId Unique order id created by the Jose Market backend; each id can be paid once.
    function payOrder(bytes32 orderId, address seller, uint256 amount) external whenNotPaused nonReentrant {
        if (seller == address(0)) revert ZeroAddress();
        if (seller == msg.sender) revert SellerIsBuyer();
        if (amount == 0) revert ZeroAmount();
        if (orderPaid[orderId]) revert OrderAlreadyPaid(orderId);
        orderPaid[orderId] = true;

        uint256 fee = amount * marketFeeBps / 10_000;
        if (fee > 0) jose.safeTransferFrom(msg.sender, treasury, fee);
        jose.safeTransferFrom(msg.sender, seller, amount - fee);
        emit OrderPaid(orderId, msg.sender, seller, amount, fee);
    }

    /// @notice Cost in JOSE base units for a number of credits at the current price.
    function quoteCredits(uint256 credits) external view returns (uint256) {
        return credits * pricePerCredit;
    }

    // ---------------------------------------------------------------- admin

    function setPricePerCredit(uint256 newPrice) external onlyOwner {
        emit PriceChanged(pricePerCredit, newPrice);
        pricePerCredit = newPrice;
    }

    function setTreasury(address newTreasury) external onlyOwner {
        if (newTreasury == address(0)) revert ZeroAddress();
        emit TreasuryChanged(treasury, newTreasury);
        treasury = newTreasury;
    }

    function setMarketFeeBps(uint16 newFeeBps) external onlyOwner {
        if (newFeeBps > MAX_FEE_BPS) revert FeeTooHigh();
        emit MarketFeeChanged(marketFeeBps, newFeeBps);
        marketFeeBps = newFeeBps;
    }

    /// @notice Emergency stop for new payments. Cannot touch anyone's tokens.
    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    /// @notice Return any token sent to this contract by mistake to the treasury.
    function rescue(IERC20 token) external onlyOwner {
        uint256 amount = token.balanceOf(address(this));
        token.safeTransfer(treasury, amount);
        emit Rescued(address(token), treasury, amount);
    }

    /// @dev Ownership can't be renounced: it would freeze the price and treasury forever.
    function renounceOwnership() public pure override {
        revert("renounce disabled");
    }
}
