// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.24;

// Intended for a Privi-approved EVM chain after security review, not deployed by this PR.
// OpenZeppelin Contracts v5.x dependencies (pin an audited release for production).
import {ERC721URIStorage} from "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @title PriviChemDataReceipt
/// @notice One data-bound NFT per chemistry record. Distinct from fungible PRIV/PRVI tokens.
///         All research content remains off-chain: only commitments and a public metadata URI.
contract PriviChemDataReceipt is ERC721URIStorage, Ownable {
    struct Commitment {
        bytes32 projectDigest;
        bytes32 reportDigest;
        bytes32 formulaDigest;
        bytes32 sourceDigest;
        bytes32 codeDigest;
        uint64 committedAt;
    }

    uint256 public nextTokenId = 1;
    mapping(uint256 => Commitment) public commitments;
    mapping(bytes32 => bool) public alreadyMinted;

    event ChemDataCommitted(uint256 indexed tokenId, address indexed holder, bytes32 indexed reportDigest,
                            bytes32 projectDigest, bytes32 formulaDigest, bytes32 sourceDigest, bytes32 codeDigest);

    constructor(address operator) ERC721("Privi Chem Data Receipt", "PCDR") Ownable(operator) {}

    /// @notice Operator-controlled issuance after authorization and provenance checks.
    /// @dev Mint transaction itself is the on-chain anchor; verify block and receipt independently.
    function mintReceipt(
        address holder, bytes32 projectDigest, bytes32 reportDigest, bytes32 formulaDigest,
        bytes32 sourceDigest, bytes32 codeDigest, string calldata metadataUri
    ) external onlyOwner returns (uint256 id) {
        require(holder != address(0), "zero holder");
        require(projectDigest != bytes32(0) && reportDigest != bytes32(0) &&
                formulaDigest != bytes32(0) && sourceDigest != bytes32(0), "empty commitment");
        require(!alreadyMinted[reportDigest], "report already minted");
        id = nextTokenId++;
        alreadyMinted[reportDigest] = true;
        commitments[id] = Commitment(projectDigest, reportDigest, formulaDigest, sourceDigest, codeDigest, uint64(block.timestamp));
        _safeMint(holder, id);
        _setTokenURI(id, metadataUri);
        emit ChemDataCommitted(id, holder, reportDigest, projectDigest, formulaDigest, sourceDigest, codeDigest);
    }
}
