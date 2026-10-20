// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Append-only IoT event commitments on the native Privi EVM chain.
/// @dev Actual sensor readings and Ed25519 signatures remain off-chain.
///      The enrolled gateway verifies source signatures before submitting.
contract PriviIoTLedger {
    error NotOwner();
    error InvalidDevice();
    error DeviceAlreadyEnrolled();
    error DeviceNotEnrolled();
    error DeviceDisabled();
    error WrongGateway();
    error WrongSequence();
    error InvalidEvent();

    address public immutable owner;

    struct Device {
        address gateway;
        bytes32 signingKeyHash;
        uint64 lastSequence;
        bool enabled;
        bool enrolled;
    }

    mapping(bytes32 => Device) public devices;

    event DeviceEnrolled(bytes32 indexed deviceIdHash, address indexed gateway, bytes32 signingKeyHash);
    event DeviceEnabled(bytes32 indexed deviceIdHash, bool enabled);
    event DeviceGatewayChanged(bytes32 indexed deviceIdHash, address indexed gateway);
    event DeviceKeyChanged(bytes32 indexed deviceIdHash, bytes32 signingKeyHash);

    // Exactly one confirmed state-changing transaction per accepted event.
    event IoTRecorded(
        bytes32 indexed deviceIdHash,
        uint64 indexed sequence,
        bytes32 indexed eventHash,
        bytes32 payloadHash,
        bytes32 eventTypeHash,
        bytes32 signatureHash,
        uint64 observedAt
    );

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    function enrollDevice(bytes32 deviceIdHash, bytes32 signingKeyHash, address gateway) external onlyOwner {
        if (deviceIdHash == bytes32(0) || signingKeyHash == bytes32(0) || gateway == address(0))
            revert InvalidDevice();
        if (devices[deviceIdHash].enrolled) revert DeviceAlreadyEnrolled();
        devices[deviceIdHash] = Device(gateway, signingKeyHash, 0, true, true);
        emit DeviceEnrolled(deviceIdHash, gateway, signingKeyHash);
    }

    function setDeviceEnabled(bytes32 deviceIdHash, bool enabled) external onlyOwner {
        Device storage d = devices[deviceIdHash];
        if (!d.enrolled) revert DeviceNotEnrolled();
        d.enabled = enabled;
        emit DeviceEnabled(deviceIdHash, enabled);
    }

    function changeDeviceGateway(bytes32 deviceIdHash, address gateway) external onlyOwner {
        Device storage d = devices[deviceIdHash];
        if (!d.enrolled) revert DeviceNotEnrolled();
        if (gateway == address(0)) revert InvalidDevice();
        d.gateway = gateway;
        emit DeviceGatewayChanged(deviceIdHash, gateway);
    }

    function changeDeviceKey(bytes32 deviceIdHash, bytes32 signingKeyHash) external onlyOwner {
        Device storage d = devices[deviceIdHash];
        if (!d.enrolled) revert DeviceNotEnrolled();
        if (signingKeyHash == bytes32(0)) revert InvalidDevice();
        d.signingKeyHash = signingKeyHash;
        emit DeviceKeyChanged(deviceIdHash, signingKeyHash);
    }

    function recordEvent(
        bytes32 deviceIdHash,
        uint64 sequence,
        uint64 observedAt,
        bytes32 eventTypeHash,
        bytes32 payloadHash,
        bytes32 eventHash,
        bytes32 signatureHash
    ) external {
        Device storage d = devices[deviceIdHash];
        if (!d.enrolled) revert DeviceNotEnrolled();
        if (!d.enabled) revert DeviceDisabled();
        if (msg.sender != d.gateway) revert WrongGateway();
        if (sequence == 0 || uint256(sequence) != uint256(d.lastSequence) + 1) revert WrongSequence();
        if (observedAt == 0 || eventTypeHash == bytes32(0) || payloadHash == bytes32(0)
            || eventHash == bytes32(0) || signatureHash == bytes32(0))
            revert InvalidEvent();

        d.lastSequence = sequence;
        emit IoTRecorded(deviceIdHash, sequence, eventHash, payloadHash, eventTypeHash, signatureHash, observedAt);
    }
}
