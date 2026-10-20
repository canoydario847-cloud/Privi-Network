// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title PriviEscrow - agent-to-agent escrow settled by Privi Guard arbiter signatures
/// @notice UNAUDITED. Not deployed by Privi yet. Test on Base Sepolia before holding real funds.
/// @dev Privi Guard (Privi Ledger MCP, guard_escrow_act) signs release/refund authorizations:
///      digest = keccak256(abi.encodePacked("PriviEscrow", block.chainid, address(this), id, action, to, amount))
///      signature = EIP-191 personal_sign over the 32-byte digest by the arbiter key.
///      action 1 = release to payee, 2 = refund to payer.
///      Safety valve: if no authorization arrives, the payer can reclaim 14 days after the deadline.

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

contract PriviEscrow {
    address public immutable arbiter;
    uint64 public constant GRACE = 14 days;

    struct Deal {
        address payer;
        address payee;
        address token;
        uint256 amount;
        uint64 deadline;
        bool settled;
    }

    mapping(bytes32 => Deal) public deals;

    event Funded(bytes32 indexed id, address indexed payer, address indexed payee, address token, uint256 amount, uint64 deadline);
    event Settled(bytes32 indexed id, uint8 action, address to, uint256 amount);

    constructor(address arbiter_) {
        require(arbiter_ != address(0), "arbiter required");
        arbiter = arbiter_;
    }

    /// @param id escrow_id_bytes32 from Privi Guard (sha256 of the esc_... id)
    function fund(bytes32 id, address payee, address token, uint256 amount, uint64 deadline) external {
        require(deals[id].payer == address(0), "escrow exists");
        require(payee != address(0) && token != address(0) && amount > 0, "bad terms");
        require(deadline > block.timestamp, "deadline passed");
        deals[id] = Deal(msg.sender, payee, token, amount, deadline, false);
        require(IERC20(token).transferFrom(msg.sender, address(this), amount), "transfer failed");
        emit Funded(id, msg.sender, payee, token, amount, deadline);
    }

    function settle(bytes32 id, uint8 action, bytes calldata signature) external {
        Deal storage d = deals[id];
        require(d.payer != address(0) && !d.settled, "not open");
        require(action == 1 || action == 2, "bad action");
        address to = action == 1 ? d.payee : d.payer;
        bytes32 digest = keccak256(abi.encodePacked("PriviEscrow", block.chainid, address(this), id, action, to, d.amount));
        require(_recover(digest, signature) == arbiter, "bad arbiter signature");
        d.settled = true;
        require(IERC20(d.token).transfer(to, d.amount), "transfer failed");
        emit Settled(id, action, to, d.amount);
    }

    function reclaimAfterGrace(bytes32 id) external {
        Deal storage d = deals[id];
        require(msg.sender == d.payer && !d.settled, "not yours or settled");
        require(block.timestamp > uint256(d.deadline) + GRACE, "grace period not over");
        d.settled = true;
        require(IERC20(d.token).transfer(d.payer, d.amount), "transfer failed");
        emit Settled(id, 2, d.payer, d.amount);
    }

    function _recover(bytes32 digest, bytes calldata sig) internal pure returns (address) {
        require(sig.length == 65, "bad signature length");
        bytes32 r = bytes32(sig[0:32]);
        bytes32 s = bytes32(sig[32:64]);
        uint8 v = uint8(sig[64]);
        require(uint256(s) <= 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0, "high s");
        bytes32 h = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", digest));
        address a = ecrecover(h, v, r, s);
        require(a != address(0), "bad signature");
        return a;
    }
}
