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

  await confirmed(await contract.setDeveloperEnabled(wallet.address,false,
    {gasLimit:200000n,gasPrice:GAS_PRICE,type:0}));
  const packet3=eventPacket(pair1.privateKey,"grid.sensorA",2,3);
  await assert.rejects(submitEvent(packet3,common),
    "revoked Privi developers must be blocked before a transaction");

  console.log(JSON.stringify({
    status:"PRIVI_ONLY_POP_IOT_DISPOSABLE_EVM_INTEGRATION_PASS",
    financial_mainnet:false,token_minted:false,
    cosmos_chain_id:"local-4221",evm_chain_id:262144,
    disposable_contract:address,
    first_position:recorded1.popStamp,
    second_position:recorded2.popStamp,
    second_transaction:recorded2.transactionHash,
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
