#!/usr/bin/env node
"use strict";
/*
 * CI-only disposable 4-container Cosmos EVM integration proof.
 * Transactional Privi IoT gateway and PoP contract tested on upstream
 * valueless atest reference chain ID 262144. NO real PRVI or mainnet.
 */
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { localGate, exportDevKey } = require("../testnet/send_disposable_test_transfer.cjs");
const { sha, packetDigest, verifyDevicePacket, submitEvent } = require("./gateway/core.cjs");
const {intentMessage,issuerBoundDigest}=require("./intents/capsule.cjs");

const RPC = "http://127.0.0.1:8545";
const EVM_ID = 262144n;
const GAS_PRICE = 10000000000n;

async function confirmed(tx) {
  const r = await tx.wait(1, 120000);
  assert(r && Number(r.status) === 1, "disposable transaction was not mined successfully");
  return r;
}

function eventPacket(key, deviceId, sequence, positionSequence) {
  const data = {
    version:3,
    companyId:"PRIVI_DISPOSABLE",
    popZone:"GRID/READINGS",
    deviceId,
    sequence,
    positionSequence,
    observedAt:1760912345,
    eventType:"temperature",
    payload:{temperatureCentidegrees:2250,humidityPercent:43}
  };
  const signature = crypto.sign(null, Buffer.from(packetDigest(data).signingText, "utf8"), key);
  data.signatureBase64 = signature.toString("base64");
  return data;
}

async function run(env = process.env) {
  localGate(env, RPC);
  const es = env.PRIVI_ETHERS_MODULE_PATH;
  const solcModule = env.PRIVI_SOLC_MODULE_PATH;
  assert(es?.includes("privi-test-ethers") && solcModule?.includes("privi-test-ethers"),
         "isolated pinned developer tools are required");
  const {ethers} = require(es);
  const solc = require(solcModule);
  assert(solc.version().startsWith("0.8.26+"), "Solidity compiler version mismatch");

  const provider = new ethers.JsonRpcProvider(RPC,{name:"privi-disposable",chainId:262144},
                                              {staticNetwork:true});
  const chain = await provider.send("eth_chainId", []);
  assert(BigInt(chain) === EVM_ID, "unexpected EVM chain identity");

  const key = exportDevKey(path.resolve(__dirname, "..", ".upstream-evm"));
  const wallet = new ethers.Wallet(key, provider);
  assert(await provider.getBalance(wallet.address) > GAS_PRICE * 7000000n,
         "disposable development wallet requires gas");

  const contractPath=path.join(__dirname, "contracts", "PriviIoTLedger.sol");
  const name="PriviIoTLedger.sol";
  const source=fs.readFileSync(contractPath,"utf8");
  const input={language:"Solidity",sources:{[name]:{content:source}},
               settings:{viaIR:true,optimizer:{enabled:true,runs:200},evmVersion:"paris",
                         outputSelection:{"*":{"*":["abi","evm.bytecode.object"]}}}};
  const output=JSON.parse(solc.compile(JSON.stringify(input)));
  const errors=(output.errors||[]).filter(x=>x.severity==="error");
  assert.equal(errors.length,0,"Solidity compiler errors");
  const built=output.contracts?.[name]?.PriviIoTLedger;
  assert(built?.evm?.bytecode?.object,"Missing compiled PoP contract");
  const factory=new ethers.ContractFactory(built.abi,"0x"+built.evm.bytecode.object,wallet);
  const contract=await factory.deploy({gasLimit:5000000n,gasPrice:GAS_PRICE,type:0});
  const deployed=await confirmed(contract.deploymentTransaction());
  const address=await contract.getAddress();
  assert(deployed.contractAddress?.toLowerCase()===address.toLowerCase(),"contract address mismatch");

  const genesis=await provider.send("eth_getBlockByNumber", ["0x0",false]);
  assert(/^0x[0-9a-f]{64}$/i.test(genesis?.hash||""),"disposable genesis unavailable");
  const code=await provider.getCode(address);
  assert(code !== "0x","Privi IoT contract missing on disposable chain");
  const config={
    mode:"development", network:"privi-native",settlementChain:"privi",
    bridgeMode:"disabled",pairingMode:"disabled",
    rpcUrl:RPC, chainId:262144,
    genesisHash:genesis.hash,
    contractAddress:address,
    contractCodeSha256:sha(Buffer.from(code.slice(2),"hex")),
    confirmations:1
  };

  const pair1=crypto.generateKeyPairSync("ed25519");
  const pair2=crypto.generateKeyPairSync("ed25519");
  const spki1=pair1.publicKey.export({format:"der",type:"spki"});
  const spki2=pair2.publicKey.export({format:"der",type:"spki"});
  const packet1=eventPacket(pair1.privateKey,"grid.sensorA",1,1);
  const packet2=eventPacket(pair2.privateKey,"grid.sensorB",1,2);
  const registry={
    "grid.sensorA": {publicKeySpkiBase64:spki1.toString("base64")},
    "grid.sensorB": {publicKeySpkiBase64:spki2.toString("base64")}
  };
  const e1=verifyDevicePacket(packet1,registry);
  const e2=verifyDevicePacket(packet2,registry);

  // Developer registration must precede any enrollment and cannot be
  // bypassed by a device or external chain integration.
  await assert.rejects(
    contract.enrollDevice.staticCall(e1.deviceIdHash,e1.signingKeyHash,e1.companyIdHash,wallet.address),
    "unregistered Privi developer must not be allowed to enroll"
  );
  await confirmed(await contract.registerDeveloper(wallet.address,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  // A registered developer is NOT enough: company participation and
  // explicit company administrator authorization are separate prerequisites.
  await assert.rejects(
    contract.enrollDevice.staticCall(e1.deviceIdHash,e1.signingKeyHash,e1.companyIdHash,wallet.address),
    "company must be registered and authorize this Privi developer"
  );
  const companyAdmin=ethers.Wallet.createRandom().connect(provider);
  await confirmed(await wallet.sendTransaction({
    to:companyAdmin.address,value:GAS_PRICE * 1000000n,gasLimit:30000n,
    gasPrice:GAS_PRICE,type:0
  }));
  await confirmed(await contract.proposeCompanyRegistration(
    e1.companyIdHash,companyAdmin.address,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  // Platform proposal must NOT register, activate or grant any company feature.
  const proposed=await contract.companies(e1.companyIdHash);
  assert.equal(proposed.registered,false,"Privi administrator proposal is not company opt-in");
  assert.equal(await contract.pendingCompanyAdministrators(e1.companyIdHash),
    companyAdmin.address);
  await assert.rejects(
    contract.acceptCompanyRegistration.staticCall(e1.companyIdHash),
    "platform owner cannot accept on behalf of company"
  );
  await assert.rejects(
    contract.enrollDevice.staticCall(e1.deviceIdHash,e1.signingKeyHash,e1.companyIdHash,wallet.address),
    "company proposal alone cannot authorize its devices"
  );
  await confirmed(await contract.connect(companyAdmin).acceptCompanyRegistration(
    e1.companyIdHash,{gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  assert.equal((await contract.companies(e1.companyIdHash)).registered,true);
  assert.equal(await contract.pendingCompanyAdministrators(e1.companyIdHash),
    ethers.ZeroAddress);
  await assert.rejects(
    contract.setCompanyGateway.staticCall(e1.companyIdHash,wallet.address,true),
    "platform owner cannot bypass independent company gateway consent"
  );

  // A company may reject an invitation; the platform can revoke an
  // unaccepted mistaken invitation without granting ANY rights.
  const declinedCompanyHash=sha(Buffer.from("PRIVI_DECLINED_CO","utf8"));
  await confirmed(await contract.proposeCompanyRegistration(
    declinedCompanyHash,companyAdmin.address,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  await assert.rejects(
    contract.acceptCompanyRegistration.staticCall(declinedCompanyHash),
    "platform cannot accept a second company invitation"
  );
  await confirmed(await contract.connect(companyAdmin).rejectCompanyRegistration(
    declinedCompanyHash,{gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  assert.equal((await contract.companies(declinedCompanyHash)).registered,false);
  assert.equal(await contract.pendingCompanyAdministrators(declinedCompanyHash),
    ethers.ZeroAddress);
  await assert.rejects(contract.connect(companyAdmin).acceptCompanyRegistration.staticCall(declinedCompanyHash),
    "a rejected invite cannot be accepted");
  const cancelledCompanyHash=sha(Buffer.from("PRIVI_CANCELLED_CO","utf8"));
  await confirmed(await contract.proposeCompanyRegistration(
    cancelledCompanyHash,companyAdmin.address,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  await confirmed(await contract.cancelCompanyRegistration(
    cancelledCompanyHash,{gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  assert.equal((await contract.companies(cancelledCompanyHash)).registered,false);
  assert.equal(await contract.pendingCompanyAdministrators(cancelledCompanyHash),
    ethers.ZeroAddress);
  await assert.rejects(
    contract.enrollDevice.staticCall(e1.deviceIdHash,e1.signingKeyHash,e1.companyIdHash,wallet.address),
    "company must approve its Privi developer gateway"
  );
  await confirmed(await contract.connect(companyAdmin).setCompanyGateway(
    e1.companyIdHash,wallet.address,true,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));

  await confirmed(await contract.enrollDevice(e1.deviceIdHash,e1.signingKeyHash,e1.companyIdHash,wallet.address,
    {gasLimit:300000n,gasPrice:GAS_PRICE,type:0}));
  await confirmed(await contract.enrollDevice(e2.deviceIdHash,e2.signingKeyHash,e2.companyIdHash,wallet.address,
    {gasLimit:300000n,gasPrice:GAS_PRICE,type:0}));

  const common={registry,config,provider,wallet,contract};
  const recorded1=await submitEvent(packet1,common);
  assert.equal(recorded1.positionSequence,1);
  assert.equal(await contract.nextPositionSequence(e1.companyIdHash,e1.popZoneHash),2n);

  // A second device must use the next company+zone position even while its
  // own device-specific sequence begins at one.
  const recorded2=await submitEvent(packet2,common);
  assert.equal(recorded2.positionSequence,2);
  assert.equal(await contract.nextPositionSequence(e2.companyIdHash,e2.popZoneHash),3n);
  assert.equal(await contract.usedPoPStamp(e1.popStampHash),true);
  assert.equal(await contract.usedPoPStamp(e2.popStampHash),true);

  await assert.rejects(submitEvent(packet1,common),
    "an already sealed PoP event must not be submitted again");

  // Gateway authorizations must NOT survive a confirmed company-admin handover.
  const successorAdmin=ethers.Wallet.createRandom().connect(provider);
  const cancelledSuccessor=ethers.Wallet.createRandom().connect(provider);
  await confirmed(await wallet.sendTransaction({
    to:successorAdmin.address,value:GAS_PRICE * 1000000n,gasLimit:30000n,
    gasPrice:GAS_PRICE,type:0
  }));
  await assert.rejects(
    contract.proposeCompanyAdministratorTransfer.staticCall(e1.companyIdHash,successorAdmin.address),
    "Privi platform owner cannot propose a company administrator transfer"
  );
  await confirmed(await contract.connect(companyAdmin).proposeCompanyAdministratorTransfer(
    e1.companyIdHash,cancelledSuccessor.address,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  await assert.rejects(
    contract.connect(successorAdmin).acceptCompanyAdministratorTransfer.staticCall(e1.companyIdHash),
    "a non-designated successor cannot accept"
  );
  await confirmed(await contract.connect(companyAdmin).cancelCompanyAdministratorTransfer(
    e1.companyIdHash,{gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  await assert.rejects(
    contract.connect(cancelledSuccessor).acceptCompanyAdministratorTransfer.staticCall(e1.companyIdHash),
    "a cancelled transfer must never succeed"
  );
  await confirmed(await contract.connect(companyAdmin).proposeCompanyAdministratorTransfer(
    e1.companyIdHash,successorAdmin.address,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  await assert.rejects(
    contract.acceptCompanyAdministratorTransfer.staticCall(e1.companyIdHash),
    "Privi owner cannot accept transfer for a company administrator"
  );
  await confirmed(await contract.connect(successorAdmin).acceptCompanyAdministratorTransfer(
    e1.companyIdHash,{gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  assert.equal((await contract.companies(e1.companyIdHash)).administrator,successorAdmin.address);
  assert.equal(await contract.companyGatewayEpoch(e1.companyIdHash),2n,
    "company gateway epoch must increase on administrator handover");
  assert.equal(await contract.companyGateways(e1.companyIdHash,wallet.address),false,
    "previous administrator's gateway permission must be invalidated");
  await assert.rejects(
    contract.connect(companyAdmin).setCompanyGateway.staticCall(
      e1.companyIdHash,wallet.address,true),
    "former administrator cannot authorize Privi gateways"
  );
  const packet3=eventPacket(pair1.privateKey,"grid.sensorA",2,3);
  await assert.rejects(submitEvent(packet3,common),
    "old developer permission must not submit following company admin handover");
  await confirmed(await contract.connect(successorAdmin).setCompanyGateway(
    e1.companyIdHash,wallet.address,true,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  assert.equal(await contract.companyGateways(e1.companyIdHash,wallet.address),true);

  // Company suspension blocks all its developers and devices immediately.
  await confirmed(await contract.setCompanyEnabled(e1.companyIdHash,false,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  await assert.rejects(submitEvent(packet3,common),
    "suspended Privi companies must not submit");
  await confirmed(await contract.setCompanyEnabled(e1.companyIdHash,true,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  await confirmed(await contract.connect(successorAdmin).setCompanyGateway(
    e1.companyIdHash,wallet.address,false,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  await assert.rejects(submitEvent(packet3,common),
    "company revocation of a gateway must block this developer");
  await confirmed(await contract.connect(successorAdmin).setCompanyGateway(
    e1.companyIdHash,wallet.address,true,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));

  // Declarative Intent Capsule: an independently controlled company wallet
  // signs the exact PoP event hash and rule bounds. No Solidity business
  // logic is deployed for each policy and no real financial PRVI is issued.
  const head=await provider.send("eth_getBlockByNumber",["latest",false]);
  const now=Number(BigInt(head.timestamp));
  const proposalDigest=packetDigest(packet3);
  const capsule={
    version:1,type:"privi.iot.record",chainId:262144,
    genesisHash:config.genesisHash,contractAddress:config.contractAddress,
    companyIdHash:proposalDigest.companyIdHash,
    deviceIdHash:proposalDigest.deviceIdHash,
    eventHash:proposalDigest.eventHash,
    popStampHash:proposalDigest.popStampHash,
    gateway:wallet.address,
    companyEpoch:Number(await contract.companyGatewayEpoch(e1.companyIdHash)),
    notBefore:now-10,expiresAt:now+300,
    nonce:"0x"+crypto.randomBytes(32).toString("hex"),
    maxGasPriceWei:GAS_PRICE.toString(),maxGasLimit:450000,
    maxTotalWei:(450000n*GAS_PRICE).toString(),
    predicates:[{field:"temperatureCentidegrees",min:2200,max:2400}]
  };
  const intentConfig={...config,requireIntentCapsules:true};
  const baseline={...common,config:intentConfig,ethers};
  await assert.rejects(submitEvent(packet3,baseline),
    /Intent Capsule is required/,
    "configured Privi gateway must never submit with an omitted signed intent");
  const formerAdminSignature=await companyAdmin.signMessage(intentMessage(capsule));
  await assert.rejects(submitEvent(packet3,{
      ...baseline,intentCapsule:{capsule,signature:formerAdminSignature}
    }),/current company administrator/,
    "former company administrator must not authorize an intent");
  const signature=await successorAdmin.signMessage(intentMessage(capsule));
  const intentResult=await submitEvent(packet3,{
    ...baseline,intentCapsule:{capsule,signature}
  });
  assert.equal(intentResult.intentCapsuleDigest,issuerBoundDigest(capsule),
    "receipt must bind to verified company intent policy");
  assert.equal(intentResult.intentWorstCaseFeeWei,capsule.maxTotalWei,
    "signed gas limit and signed unit fee must bound worst-case devnet cost");
  assert.equal(await contract.nextPositionSequence(e1.companyIdHash,e1.popZoneHash),4n);
  await assert.rejects(submitEvent(packet3,{
    ...baseline,intentCapsule:{capsule,signature}
  }),/sequence/,
    "replay of a signed capsule must not resubmit a sealed Privi event");

  await confirmed(await contract.setDeveloperEnabled(wallet.address,false,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  const packet4=eventPacket(pair1.privateKey,"grid.sensorA",3,4);
  await assert.rejects(submitEvent(packet4,common),
    "revoked Privi developers must be blocked before a transaction");

  console.log(JSON.stringify({
    status:"PRIVI_ONLY_POP_IOT_DISPOSABLE_EVM_INTEGRATION_PASS",
    financial_mainnet:false,token_minted:false,
    cosmos_chain_id:"local-4221",evm_chain_id:262144,
    disposable_contract:address,
    first_position:recorded1.popStamp,
    second_position:recorded2.popStamp,
    second_transaction:recorded2.transactionHash,
    company_enrollment:"two_phase_independent_consent_enforced",
    company_gateway_authorization:"enforced_independent_administrator",
    company_admin_handover:"two_party_signoff",
    former_gateway_authorizations:"invalidated_by_epoch_advance",
    signed_intent_capsule:"admin_EIP191_bounded_non_turing_complete_IoT_action",
    company_intent_fee_cap:"enforced_at_submit_on_valueless_devnet",
    company_suspension_and_revocation:"enforced",
    developer_enrollment:"enforced",
    developer_revocation:"enforced",
    second_sensor_position:"company-zone ordered",
    replay_protection:"enforced",
    source:"disposable upstream Cosmos EVM, not deployed PoP consensus"
  },null,2));
}

if(require.main === module){
  run().catch(error => {
    console.error("Privi PoP IoT disposable integration failed: "
      +String(error?.shortMessage||error?.message||"unknown").slice(0,200));
    process.exitCode=1;
  });
}
module.exports={run,eventPacket};
