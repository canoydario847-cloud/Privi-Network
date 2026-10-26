// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/*
 * Privi World Co. — Privi / native-USDC Base starter liquidity.
 * INITIAL PRICE = 1 PRIVI per 1 USDC, NOT a redeemable $1 peg.
 * No payroll-index oracle or rebalancing mechanism is implemented.
 * Uniswap v3, Base mainnet only. Review and test before funding.
 */

interface IPriviERC20 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
    function approve(address spender, uint256 value) external returns (bool);
}

interface IPriviUniV3Factory {
    function getPool(address tokenA, address tokenB, uint24 fee)
        external view returns (address);
}

interface IPriviUniV3PositionManager {
    struct MintParams {
        address token0;
        address token1;
        uint24 fee;
        int24 tickLower;
        int24 tickUpper;
        uint256 amount0Desired;
        uint256 amount1Desired;
        uint256 amount0Min;
        uint256 amount1Min;
        address recipient;
        uint256 deadline;
    }

    function createAndInitializePoolIfNecessary(
        address token0, address token1, uint24 fee, uint160 sqrtPriceX96
    ) external payable returns (address pool);

    function mint(MintParams calldata params)
        external payable
        returns (uint256 tokenId, uint128 liquidity, uint256 amount0, uint256 amount1);
}

contract PriviBaseOneToOnePool {
    // Numeric literals include two extra leading hex zeros to avoid address-checksum
    // presentation issues in editors; the resulting uint160 is the same 20-byte address.
    address public constant USDC = address(uint160(0x00833589fcd6edb6e08f4c7c32d4f71b54bda02913));
    address public constant PRIVI = address(uint160(0x00a11626baf87524e61b5697634c7ec48d26279d6c));
    address public constant FACTORY = address(uint160(0x0033128a8fc17869897dce68ed026d694621f6fdfd));
    address public constant POSITION_MANAGER = address(uint160(0x0003a520b32c04bf3beef7beb72e919cf822ed34f1));

    // USDC is token0 and PRIVI is token1 by address ordering on Base.
    // 1 whole USDC = 10^6 units; 1 whole PRIVI = 10^18 units.
    // token1/token0 raw ratio is 10^12 for a 1:1 whole-token price.
    uint160 public constant INITIAL_SQRT_PRICE_X96 = uint160(uint256(1_000_000) << 96);
    uint256 public constant PRIVI_PER_USDC_RAW = 1_000_000_000_000;
    uint256 public constant MAX_USDC_RAW = 1_000_000 * 1e6;
    uint24 public constant POOL_FEE = 3000; // 0.30%
    int24 public constant LOWER_TICK = -887220; // full-range ticks, divisible by 60
    int24 public constant UPPER_TICK = 887220;

    address public immutable owner;
    bool public launched;
    uint256 private _entered = 1;

    event PoolFunded(
        address indexed pool, address indexed owner, uint256 indexed positionId,
        uint256 usdcCommitted, uint256 priviCommitted,
        uint256 usdcReturned, uint256 priviReturned
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "Not the deploying wallet");
        _;
    }

    modifier nonReentrant() {
        require(_entered == 1, "Reentrant call");
        _entered = 2;
        _;
        _entered = 1;
    }

    constructor() {
        require(block.chainid == 8453, "Deploy ONLY on Base mainnet");
        require(USDC < PRIVI, "Unexpected token ordering");
        owner = msg.sender;
    }

    /// @notice Returns maximum matched deposits in RAW units, based on current
    /// balances of the wallet which deployed this contract.
    function preview() public view returns (uint256 usdcRaw, uint256 priviRaw) {
        uint256 usdcOwned = IPriviERC20(USDC).balanceOf(owner);
        uint256 priviOwned = IPriviERC20(PRIVI).balanceOf(owner);
        usdcRaw = usdcOwned;
        if (usdcRaw > MAX_USDC_RAW) usdcRaw = MAX_USDC_RAW;
        uint256 maxUsdcBackedByPrivi = priviOwned / PRIVI_PER_USDC_RAW;
        if (usdcRaw > maxUsdcBackedByPrivi) usdcRaw = maxUsdcBackedByPrivi;
        priviRaw = usdcRaw * PRIVI_PER_USDC_RAW;
    }

    /// @notice One-time liquidity creation; will not add to any existing 0.3% pool.
    /// @param expectedUsdcRaw Exactly the current first return value of preview().
    function createAndFund(uint256 expectedUsdcRaw)
        external onlyOwner nonReentrant
        returns (address pool, uint256 positionId, uint256 usedUSDC, uint256 usedPRIVI)
    {
        require(!launched, "Already launched");
        (uint256 usdcRaw, uint256 priviRaw) = preview();
        require(usdcRaw != 0 && usdcRaw == expectedUsdcRaw, "Balance changed or amount wrong");
        require(
            IPriviUniV3Factory(FACTORY).getPool(USDC, PRIVI, POOL_FEE) == address(0),
            "Pool already exists; inspect market and use official UI"
        );

        launched = true;
        _safeTransferFrom(USDC, owner, address(this), usdcRaw);
        _safeTransferFrom(PRIVI, owner, address(this), priviRaw);
        _forceApprove(USDC, POSITION_MANAGER, usdcRaw);
        _forceApprove(PRIVI, POSITION_MANAGER, priviRaw);

        pool = IPriviUniV3PositionManager(POSITION_MANAGER)
            .createAndInitializePoolIfNecessary(USDC, PRIVI, POOL_FEE, INITIAL_SQRT_PRICE_X96);

        // Nonzero minima provide 1% limits against unfavorable execution.
        IPriviUniV3PositionManager.MintParams memory params =
            IPriviUniV3PositionManager.MintParams({
                token0: USDC,
                token1: PRIVI,
                fee: POOL_FEE,
                tickLower: LOWER_TICK,
                tickUpper: UPPER_TICK,
                amount0Desired: usdcRaw,
                amount1Desired: priviRaw,
                amount0Min: (usdcRaw * 99) / 100,
                amount1Min: (priviRaw * 99) / 100,
                recipient: owner, // position NFT always goes to your wallet
                deadline: block.timestamp + 300
            });

        uint128 liquidity;
        (positionId, liquidity, usedUSDC, usedPRIVI) =
            IPriviUniV3PositionManager(POSITION_MANAGER).mint(params);
        require(liquidity > 0 && usedUSDC > 0 && usedPRIVI > 0, "No usable liquidity");

        _forceApprove(USDC, POSITION_MANAGER, 0);
        _forceApprove(PRIVI, POSITION_MANAGER, 0);
        uint256 refundUSDC = IPriviERC20(USDC).balanceOf(address(this));
        uint256 refundPRIVI = IPriviERC20(PRIVI).balanceOf(address(this));
        if (refundUSDC != 0) _safeTransfer(USDC, owner, refundUSDC);
        if (refundPRIVI != 0) _safeTransfer(PRIVI, owner, refundPRIVI);

        emit PoolFunded(pool, owner, positionId, usedUSDC, usedPRIVI, refundUSDC, refundPRIVI);
    }

    function _safeTransfer(address token, address to, uint256 amount) internal {
        _callToken(token, abi.encodeWithSelector(IPriviERC20.transfer.selector, to, amount));
    }

    function _safeTransferFrom(address token, address from, address to, uint256 amount) internal {
        _callToken(token, abi.encodeWithSelector(IPriviERC20.transferFrom.selector, from, to, amount));
    }

    function _forceApprove(address token, address spender, uint256 amount) internal {
        _callToken(token, abi.encodeWithSelector(IPriviERC20.approve.selector, spender, 0));
        if (amount > 0) {
            _callToken(token, abi.encodeWithSelector(IPriviERC20.approve.selector, spender, amount));
        }
    }

    function _callToken(address token, bytes memory data) internal {
        (bool success, bytes memory result) = token.call(data);
        require(success && (result.length == 0 || abi.decode(result, (bool))), "Token transfer/approval failed");
    }
}
