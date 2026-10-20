# Privi-only IoT ledger and local AI data labeling

Status: DEVELOPMENT ONLY. Draft feature, not a public Privi mainnet, real
PRVI rewards, or deployed financial application.

## Exclusive Privi developer access to the official IoT feature

Using the official Privi IoT contract requires a **Privi-registered developer
EVM address**. The Privi contract administrator alone calls registerDeveloper
to enroll a developer's authorized gateway address. Only active registered
developer gateways may enroll devices and submit IoT records. The administrator
may suspend or revoke developer access with setDeveloperEnabled. On every
recordEvent the contract rejects unregistered, disabled, or wrong gateways.
The gateway independently checks this registration before signing and sending.

This is the required Privi integration for official IoT data transactions:
- a Privi developer gateway enrollment on the Privi ledger;
- a Privi-native contract address and pinned chain/genesis/bytecode identity;
- an authenticated device enrolled through Privi by the owner;
- Privi-only ledger event receipts, then local AI data classification.

No Base, BNB, Ethereum mainnet, third-party token pair or automatic bridge
can substitute for the Privi native registration. Production submission
is intentionally disabled until a signed and audited Privi mainnet release
exists. The current network ID 262144 is an upstream *disposable developer
chain* reference; it is NOT a launched Privi-native mainnet.

This access control applies to official Privi software and deployed Privi
contracts. It cannot stop independent parties worldwide from writing other
IoT or AI software, nor make non-Privi code automatically require Privi.
Independent intellectual-property or licensing enforcement requires legal
review; third-party integration contracts must be voluntary and explicit.
No PRVI payment or bridge is required merely to register during testing.

## Company onboarding (official Privi enterprise features only)

Companies that opt into the official service must be registered on the
Privi-native ledger. The platform first proposes registration; the company
administrator must explicitly accept it from their separate wallet before
any IoT device can be enrolled or submit transactions. A Privi developer registration alone is not sufficient:
the company's own administrator must separately authorize that developer's
gateway. Only the registered company administrator can authorize or revoke gateways;
Privi's platform owner cannot authorize gateways on the company's behalf.
A company suspension or gateway revocation immediately blocks new
IoT event transactions, even if a device has already been enrolled.

Owner-side registration sequence on the Privi *developer test contract*:

    registerDeveloper(gatewayAddress)
    proposeCompanyRegistration(sha256CompanyId, companyAdministratorAddress)
    acceptCompanyRegistration(sha256CompanyId)  # called ONLY by company administrator
    setCompanyGateway(sha256CompanyId, gatewayAddress, true)
    enrollDevice(deviceIdHash, deviceEd25519KeyHash, sha256CompanyId, gatewayAddress)

Disable with `setCompanyEnabled(sha256CompanyId, false)` or have the
company administrator call `setCompanyGateway(sha256CompanyId, gatewayAddress, false)`.
The gateway independently checks the company registry and its authorization
for every accepted packet. An unregistered company cannot use the official
Privi IoT settlement feature. These controls cannot force companies to use
Privi for unrelated software or prevent independent competing blockchains.

See `production-network/enterprise/PRIVI_NATIVE_COMPANY_POLICY.md`.

## Company administrator handover (development-only)

The currently registered company administrator may propose a **different**
successor wallet using `proposeCompanyAdministratorTransfer(companyIdHash, successor)`.
Only the proposed successor may call `acceptCompanyAdministratorTransfer(companyIdHash)`;
the original administrator may call `cancelCompanyAdministratorTransfer(companyIdHash)`
before acceptance. The Privi platform owner CANNOT initiate or accept a company
administrator change on the enterprise's behalf.

On successful acceptance, the contract increments a company-specific
gateway authorization epoch and thereby **revokes every previous developer
gateway approval atomically**, including approvals that formerly returned
true through `companyGateways(companyIdHash, gateway)`. The new administrator
must explicitly authorize any existing gateway again. Previously enrolled
devices may resume only when their assigned developer gateway is newly
approved. Company suspensions and developer revocations continue to apply.

This is a mutually agreed wallet handover, NOT lost-key recovery. If a company
loses its current administrator key, it cannot use this mechanism; a separate
independently reviewed recovery policy and threshold authorization would
be required. Do not store company or gateway private keys in a repository.

## Pipeline

1. Owner registers an official Privi developer gateway and proposes a company
   account; the company administrator accepts the registration independently
   and then explicitly authorizes the gateway.
2. Owner enrolls a named authorized device and its Ed25519 public-key hash
   to that active developer gateway.
3. Device generates a canonical signed PoP-v3 JSON event containing companyId,
   popZone, per-device monotonic sequence, independent company/zone
   positionSequence, Unix-seconds observedAt, eventType and JSON payload.
4. Device signs the exact canonical signing text with its Ed25519 secret.
5. Gateway verifies packet signatures and local registry, verifies configured
   Privi EVM ID, genesis hash, contract code hash, active developer, active company,
   company-approved gateway authorization, and enabled device enrollment.
6. Gateway may opt into one signed Privi transaction per accepted event; it
   waits for an actual receipt and confirms a matching IoTRecorded log.
7. Only verified event hashes and receipt metadata are optionally indexed in
   SQLite; raw payloads and signing keys are not saved by default.
8. A local Naive Bayes AI-style classifier suggests a descriptive category
   and confidence; it does not decide or mint financial rewards.

## Packet example

{
  "version": 3,
  "companyId": "PRIVI_FACTORY",
  "popZone": "GRID/READINGS",
  "deviceId": "factory.temperature-17",
  "sequence": 1,
  "positionSequence": 1,
  "observedAt": 1760912345,
  "eventType": "temperature",
  "payload": {"temperatureCentidegrees": 2250, "humidityPercent": 44},
  "signatureBase64": "REPLACE_WITH_VALID_ED25519_SIGNATURE"
}

All payload field keys sort alphabetically at every nesting level before
hashing. Numbers MUST be safe integers; use scaled integer units for fractional
sensor data. The signing text is compact JSON of the array:

[3, companyId, deviceId, sequence, positionSequence, observedAt, popZone, popStamp, eventType, SHA256(payload_canonical_json)]

Hashes are lowercase 0x-prefixed SHA-256 hex. Each device sequence starts at 1 and increases by exactly one per mined
signed-device event. Independently, each company+zone starts positionSequence
at 1 and increments across ALL devices belonging to that company and zone.
The contract, gateway and SQLite receipt index reject duplicate, skipped or
replayed positions. Device IDs should be pseudonyms.

A local registry JSON maps deviceId to publicKeySpkiBase64. Only public keys
go in the registry, never signing secrets. Owner-side Privi contract actions:
- registerDeveloper(authorizedGatewayEvmAddress)
- proposeCompanyRegistration(companyIdHash, companyAdministratorAddress)
- acceptCompanyRegistration(companyIdHash)  // company administrator only
- rejectCompanyRegistration(companyIdHash)  // optional decline by company administrator
- cancelCompanyRegistration(companyIdHash)  // platform can cancel pending proposals ONLY
- setCompanyGateway(companyIdHash, authorizedGatewayEvmAddress, true)
- enrollDevice(sha256DeviceId, sha256DerEd25519PubKey,
  sha256CompanyId, gatewayAddress)
- setDeveloperEnabled(gatewayAddress, false) revokes gateway access.
- setDeviceEnabled(deviceIdHash, false) revokes one device.

Privi IoT contract records commitments; it does NOT prove the truth of sensor
measurements or verify Ed25519 signatures inside Solidity. The authorized
gateway handles actual Ed25519 checks and ownership authentication.

## Environment

Configuration is supplied by PRIVI_IOT_CHAIN_CONFIG pointing to a trusted
file, containing:

{
  "mode": "development",
  "network": "privi-native",
  "settlementChain": "privi",
  "bridgeMode": "disabled",
  "pairingMode": "disabled",
  "rpcUrl": "http://127.0.0.1:8545",
  "chainId": 262144,
  "genesisHash": "REPLACE_WITH_0x_PLUS_64_HEX",
  "contractAddress": "REPLACE_WITH_0x_PLUS_40_HEX",
  "contractCodeSha256": "REPLACE_WITH_0x_PLUS_64_HEX",
  "confirmations": 2
}

Pin the genesis and deployed code hashes from a trusted authenticated
source. The prototype requires loopback RPC and development mode, refusing
public or financial mainnet submission. Both Privi and developer registration
must match independently at the contract level. No public mainnet RPC,
production deployment, validator infrastructure or issuance is provided.

Local signature preview (no blockchain send) uses Node >=20:

    export PRIVI_IOT_CHAIN_CONFIG=/trusted/chain-test.json
    export PRIVI_IOT_DEVICE_REGISTRY=/trusted/device-public-keys.json
    node production-network/iot/gateway/ingest.cjs < signed-packet.json

For a disposable *developer-only* EVM, with an actual previously deployed
Privi IoT Solidity contract and developer/device enrollment, use isolated
ethers@6.15.0, set PRIVI_IOT_ENABLE_SUBMISSION=DEV_ONLY and provide a
disposable PRIVI_IOT_GATEWAY_PRIVATE_KEY securely. Set PRIVI_IOT_DB_PATH
for a local SQLite index. No mainnet transfers are enabled or recommended.
Do not commit secret keys or production data.

## AI labeling and proposed PRVI value

Local model predicts one category among environment, energy, industrial,
mobility, agriculture, building, health_device, network or other.
Confidence below 0.75 requests human review. The category is a suggestion,
not a security or financial authorization.

A deterministic *nonfinancial proposal* uses the Point of Position model
from your published research paper, computed from confirmed company-report
count R and elapsed verified Privi block days D:

    F = min(1, R / 50)
    T = min(1, D / 365)
    L = 1 + 1.5 * (0.6 * F + 0.4 * T)
    proposed_micro_prvi = zone_base_micro_prvi * L

The code uses integer basis-point arithmetic, with capped zone-specific
reference units. This is NOT a market rate or automatic exchange value.

There is no real native PRVI mint, transfer, price, payout, entitlement,
wallet balance, or promise that the provisional quote will ever be paid.
Token emission must have anti-spam controls, validated tokenomics, cost
limits, supply accounting, independent audits and release approval before
on-chain rewards are considered. AI categories do not influence the quote.
For raw payload privacy, only hashes and metadata are stored by default.

Run classifier offline without a blockchain transaction:

    python3 production-network/iot/ai_data_db.py label --packet event.json

The optional SQLite receipt index has unique transaction, event and
device-plus-sequence constraints. Do not blindly re-submit after an
indexing failure: a confirmed Privi transaction must be reconciled first.

## Adapter policy

MQTT, HTTPS, CoAP, BLE, Zigbee and LoRaWAN integration each require a
separate owner-authorized adapter that produces the signed packet format.
No code can turn on global internet IoT monitoring or claim universal access.
Developers must opt in and own or have permission for the devices.

## Tests

    node --test production-network/iot/gateway/test_core.cjs
    python3 -m unittest discover -s production-network/iot/tests -p 'test_*.py' -v

CI additionally compiles the contract with pinned solc 0.8.26. Tests prove
only this isolated feature implementation, not a deployed audited chain.
