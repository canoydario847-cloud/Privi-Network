// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Append-only IoT event commitments on the native Privi EVM chain.
/// @dev Actual sensor readings and Ed25519 signatures remain off-chain.
///      The enrolled gateway verifies source signatures before submitting.
contract PriviIoTLedger {
    error NotOwner();
    error DeveloperNotRegistered();
    error DeveloperAlreadyRegistered();
    error DeveloperDisabled();
    error CompanyNotRegistered();
    error CompanyAlreadyRegistered();
    error CompanyRegistrationPending();
    error CompanyRegistrationNotPending();
    error CompanyDisabled();
    error CompanyGatewayNotAuthorized();
    error NotCompanyAdministrator();
    error InvalidDevice();
    error DeviceAlreadyEnrolled();
    error DeviceNotEnrolled();
    error DeviceDisabled();
    error WrongGateway();
    error WrongSequence();
    error WrongPositionSequence();
    error DuplicatePoPPosition();
    error InvalidEvent();

    address public immutable owner;

    struct Device {
        address gateway;
        bytes32 signingKeyHash;
        uint64 lastSequence;
        bool enabled;
        bool enrolled;
        bytes32 companyIdHash;
    }

    mapping(bytes32 => Device) public devices;
    // Position sequence belongs to each company + zone, NOT each device.
    // This prevents two sensors at one company using the same PoP position.
    mapping(bytes32 => uint64) public popLastPosition;
    mapping(bytes32 => bool) public usedPoPStamp;

    function positionKey(bytes32 companyIdHash, bytes32 popZoneHash) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(companyIdHash, popZoneHash));
    }

    function nextPositionSequence(bytes32 companyIdHash, bytes32 popZoneHash) external view returns (uint64) {
        uint64 current = popLastPosition[positionKey(companyIdHash, popZoneHash)];
        if (current == type(uint64).max) revert WrongPositionSequence();
        return current + 1;
    }

    // An official Privi developer account is mandatory for this contract's feature.
    // Only the Privi administrator grants/revokes access; no third-party
    // blockchain or automatic token pairing is an accepted substitute.
    struct Developer {
        bool registered;
        bool enabled;
    }
    mapping(address => Developer) public developers;

    // Privi-native enterprise participation is an explicit opt-in.
    // Company access is scoped to official Privi features only, not to
    // the company's choice of unrelated networks or software.
    struct Company {
        address administrator;
        bool registered;
        bool enabled;
    }
    mapping(bytes32 => Company) public companies;
    // The platform can propose onboarding but CANNOT activate a company.
    // Only the designated company's independent administrator can accept.
    mapping(bytes32 => address) public pendingCompanyAdministrators;
    mapping(bytes32 => mapping(address => bool)) public companyGateways;

    event CompanyRegistrationProposed(bytes32 indexed companyIdHash, address indexed administrator);
    event CompanyRegistrationRejected(bytes32 indexed companyIdHash, address indexed administrator);
    event CompanyRegistered(bytes32 indexed companyIdHash, address indexed administrator);
    event CompanyEnabled(bytes32 indexed companyIdHash, bool enabled);
    event CompanyGatewayAuthorized(bytes32 indexed companyIdHash, address indexed gateway, bool authorized);

    event DeveloperRegistered(address indexed developer);
    event DeveloperEnabled(address indexed developer, bool enabled);

    event DeviceEnrolled(bytes32 indexed deviceIdHash, address indexed gateway, bytes32 signingKeyHash, bytes32 companyIdHash);
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
        uint64 observedAt,
        bytes32 popStampHash,
        bytes32 popZoneHash,
        uint64 positionSequence
    );

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    function registerDeveloper(address developer) external onlyOwner {
        if (developer == address(0)) revert InvalidDevice();
        if (developers[developer].registered) revert DeveloperAlreadyRegistered();
        developers[developer] = Developer(true, true);
        emit DeveloperRegistered(developer);
    }

    function setDeveloperEnabled(address developer, bool enabled) external onlyOwner {
        Developer storage d = developers[developer];
        if (!d.registered) revert DeveloperNotRegistered();
        d.enabled = enabled;
        emit DeveloperEnabled(developer, enabled);
    }

    function requireActiveDeveloper(address developer) internal view {
        Developer storage d = developers[developer];
        if (!d.registered) revert DeveloperNotRegistered();
        if (!d.enabled) revert DeveloperDisabled();
    }

    // Proposal is NOT enrollment. The Privi owner cannot impersonate
    // customer authorization or activate a company by itself.
    function proposeCompanyRegistration(bytes32 companyIdHash, address administrator) external onlyOwner {
        if (companyIdHash == bytes32(0) || administrator == address(0)) revert InvalidDevice();
        if (companies[companyIdHash].registered) revert CompanyAlreadyRegistered();
        if (pendingCompanyAdministrators[companyIdHash] != address(0)) revert CompanyRegistrationPending();
        pendingCompanyAdministrators[companyIdHash] = administrator;
        emit CompanyRegistrationProposed(companyIdHash, administrator);
    }

    // Independent wallet acknowledgement makes enterprise access opt-in.
    function acceptCompanyRegistration(bytes32 companyIdHash) external {
        address administrator = pendingCompanyAdministrators[companyIdHash];
        if (administrator == address(0)) revert CompanyRegistrationNotPending();
        if (msg.sender != administrator) revert NotCompanyAdministrator();
        delete pendingCompanyAdministrators[companyIdHash];
        companies[companyIdHash] = Company(administrator, true, true);
        emit CompanyRegistered(companyIdHash, administrator);
    }

    // Proposed administrators may decline before the platform has access.
    function rejectCompanyRegistration(bytes32 companyIdHash) external {
        address administrator = pendingCompanyAdministrators[companyIdHash];
        if (administrator == address(0)) revert CompanyRegistrationNotPending();
        if (msg.sender != administrator) revert NotCompanyAdministrator();
        delete pendingCompanyAdministrators[companyIdHash];
        emit CompanyRegistrationRejected(companyIdHash, administrator);
    }

    function setCompanyEnabled(bytes32 companyIdHash, bool enabled) external onlyOwner {
        if (!companies[companyIdHash].registered) revert CompanyNotRegistered();
        companies[companyIdHash].enabled = enabled;
        emit CompanyEnabled(companyIdHash, enabled);
    }

    function setCompanyGateway(bytes32 companyIdHash, address gateway, bool authorized) external {
        Company storage company = companies[companyIdHash];
        if (!company.registered) revert CompanyNotRegistered();
        if (msg.sender != company.administrator) revert NotCompanyAdministrator();
        if (authorized) {
            if (!company.enabled) revert CompanyDisabled();
            requireActiveDeveloper(gateway);
        }
        if (gateway == address(0)) revert InvalidDevice();
        companyGateways[companyIdHash][gateway] = authorized;
        emit CompanyGatewayAuthorized(companyIdHash, gateway, authorized);
    }

    function requireActiveCompanyGateway(bytes32 companyIdHash, address gateway) internal view {
        Company storage company = companies[companyIdHash];
        if (!company.registered) revert CompanyNotRegistered();
        if (!company.enabled) revert CompanyDisabled();
        if (!companyGateways[companyIdHash][gateway]) revert CompanyGatewayNotAuthorized();
    }

    function enrollDevice(bytes32 deviceIdHash, bytes32 signingKeyHash, bytes32 companyIdHash, address gateway) external onlyOwner {
        requireActiveDeveloper(gateway);
        requireActiveCompanyGateway(companyIdHash, gateway);
        if (deviceIdHash == bytes32(0) || signingKeyHash == bytes32(0) ||
            companyIdHash == bytes32(0) || gateway == address(0))
            revert InvalidDevice();
        if (devices[deviceIdHash].enrolled) revert DeviceAlreadyEnrolled();
        devices[deviceIdHash] = Device(gateway, signingKeyHash, 0, true, true, companyIdHash);
        emit DeviceEnrolled(deviceIdHash, gateway, signingKeyHash, companyIdHash);
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
        requireActiveDeveloper(gateway);
        requireActiveCompanyGateway(d.companyIdHash, gateway);
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
        bytes32 signatureHash,
        bytes32 popStampHash,
        bytes32 popZoneHash,
        uint64 positionSequence
    ) external {
        Device storage d = devices[deviceIdHash];
        if (!d.enrolled) revert DeviceNotEnrolled();
        if (!d.enabled) revert DeviceDisabled();
        if (msg.sender != d.gateway) revert WrongGateway();
        requireActiveDeveloper(msg.sender);
        requireActiveCompanyGateway(d.companyIdHash, msg.sender);
        if (sequence == 0 || uint256(sequence) != uint256(d.lastSequence) + 1) revert WrongSequence();
        if (positionSequence == 0 || observedAt == 0 || eventTypeHash == bytes32(0) || payloadHash == bytes32(0)
            || eventHash == bytes32(0) || signatureHash == bytes32(0) ||
            popStampHash == bytes32(0) || popZoneHash == bytes32(0))
            revert InvalidEvent();

        bytes32 key = positionKey(d.companyIdHash, popZoneHash);
        if (uint256(positionSequence) != uint256(popLastPosition[key]) + 1) revert WrongPositionSequence();
        if (usedPoPStamp[popStampHash]) revert DuplicatePoPPosition();
        d.lastSequence = sequence;
        popLastPosition[key] = positionSequence;
        usedPoPStamp[popStampHash] = true;
        emit IoTRecorded(deviceIdHash, sequence, eventHash, payloadHash, eventTypeHash,
                         signatureHash, observedAt, popStampHash, popZoneHash, positionSequence);
    }
}
