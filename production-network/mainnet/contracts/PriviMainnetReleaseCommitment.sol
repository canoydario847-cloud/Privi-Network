// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.24;

/// @title PriviMainnetReleaseCommitment
/// @notice An evidence registry only. Does not issue PRVI, authorize a genesis,
///         operate validators, approve financial launch, or prove signatures.
/// @dev Intended for later deployment on an independently approved EVM network.
contract PriviMainnetReleaseCommitment {
    address public owner;
    address public pendingOwner;
    uint256 public nextRelease = 1;

    struct Release {
        bytes32 genesisSha256;
        bytes32 binarySha256;
        bytes32 sourceCommitSha256;
        bytes32 evidenceManifestSha256;
        bytes32 chainIdDigest;
        uint256 recordedAt;
        address recorder;
    }
    mapping(uint256 => Release) private releases;
    mapping(bytes32 => bool) public genesisRecorded;
    event ReleaseRecorded(
        uint256 indexed releaseId,
        bytes32 indexed genesisSha256,
        bytes32 indexed binarySha256,
        bytes32 sourceCommitSha256,
        bytes32 evidenceManifestSha256,
        bytes32 chainIdDigest
    );
    event OwnerTransferStarted(address indexed from, address indexed to);
    event OwnerTransferCompleted(address indexed from, address indexed to);

    error NotOwner();
    error NotPendingOwner();
    error InvalidAddress();
    error EmptyCommitment();
    error DuplicateGenesis();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor(address initialOwner) {
        if (initialOwner == address(0)) revert InvalidAddress();
        owner = initialOwner;
    }

    function nominateOwner(address candidate) external onlyOwner {
        if (candidate == address(0) || candidate == owner) revert InvalidAddress();
        pendingOwner = candidate;
        emit OwnerTransferStarted(owner, candidate);
    }

    function acceptOwnership() external {
        if (msg.sender != pendingOwner) revert NotPendingOwner();
        address previous = owner;
        owner = msg.sender;
        pendingOwner = address(0);
        emit OwnerTransferCompleted(previous, owner);
    }

    /// @notice Record independently generated cryptographic digests only.
    /// @dev All bytes32 arguments are input declarations; no chain validation is performed.
    function recordRelease(
        bytes32 genesisSha256,
        bytes32 binarySha256,
        bytes32 sourceCommitSha256,
        bytes32 evidenceManifestSha256,
        bytes32 chainIdDigest
    ) external onlyOwner returns (uint256 releaseId) {
        if (genesisSha256 == bytes32(0) || binarySha256 == bytes32(0) ||
            sourceCommitSha256 == bytes32(0) || evidenceManifestSha256 == bytes32(0) ||
            chainIdDigest == bytes32(0)) revert EmptyCommitment();
        if (genesisRecorded[genesisSha256]) revert DuplicateGenesis();
        releaseId = nextRelease++;
        genesisRecorded[genesisSha256] = true;
        releases[releaseId] = Release({
            genesisSha256: genesisSha256,
            binarySha256: binarySha256,
            sourceCommitSha256: sourceCommitSha256,
            evidenceManifestSha256: evidenceManifestSha256,
            chainIdDigest: chainIdDigest,
            recordedAt: block.timestamp,
            recorder: msg.sender
        });
        emit ReleaseRecorded(
            releaseId, genesisSha256, binarySha256, sourceCommitSha256,
            evidenceManifestSha256, chainIdDigest
        );
    }

    function getRelease(uint256 id) external view returns (Release memory) {
        return releases[id];
    }
}
