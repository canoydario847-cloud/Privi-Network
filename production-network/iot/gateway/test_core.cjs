"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const {
  sha, packetDigest, verifyDevicePacket, validateNetworkConfig,
  assertPriviChain, submitEvent
} = require("./core.cjs");

function fixture() {
  const {publicKey, privateKey} = crypto.generateKeyPairSync("ed25519");
  const spki = publicKey.export({format:"der",type:"spki"});
  const packet = {
    version:1,deviceId:"sensor-01",sequence:1,observedAt:1760912345,
    eventType:"temperature",payload:{temperatureC:22,humidityPct:46}
  };
  const signature = crypto.sign(null, Buffer.from(packetDigest(packet).signingText,"utf8"),privateKey);
  packet.signatureBase64 = signature.toString("base64");
  return {packet,registry:{"sensor-01":{publicKeySpkiBase64:spki.toString("base64")}},
          signingKeyHash:sha(spki)};
}

function configuration() {
  return {
    rpcUrl:"http://127.0.0.1:8545",mode:"development",chainId:262144,
    network:"privi-native",settlementChain:"privi",bridgeMode:"disabled",pairingMode:"disabled",
    genesisHash:"0x"+"a".repeat(64),contractAddress:"0x"+"1".repeat(40),
    contractCodeSha256:sha(Buffer.from("60006000","hex")),confirmations:2
  };
}

function mocks(f, config=configuration()) {
  const provider = { send: async (method,args) => {
    if (method==="eth_chainId") return "0x40000";
    if (method==="eth_getBlockByNumber") return {hash:config.genesisHash};
    if (method==="eth_getCode") return "0x60006000";
    throw Error("Unexpected RPC "+method);
  }};
  const wallet = {address:"0x"+"3".repeat(40),provider};
  const id = packetDigest(f.packet);
  let calls=0;
  const contract = {
    runner:wallet,
    getAddress:async()=>config.contractAddress,
    developers:async()=>({registered:true,enabled:true}),
    devices:async()=>({gateway:wallet.address,signingKeyHash:f.signingKeyHash,lastSequence:0n,
                        enabled:true,enrolled:true}),
    recordEvent:async (...args)=>{
      calls++;
      assert.equal(args[0],id.deviceIdHash);
      assert.equal(args[4],id.payloadHash);
      return {hash:"0x"+"9".repeat(64),wait:async()=>({
        status:1,blockNumber:41,logs:[{address:config.contractAddress,topic:"privi-iot"}]
      })};
    },
    interface:{parseLog:log=>{
      if (log.topic!=="privi-iot") throw Error("Wrong log");
      return {name:"IoTRecorded",args:{
        deviceIdHash:id.deviceIdHash,sequence:1n,eventHash:id.eventHash
      }};
    }}
  };
  return {provider,wallet,contract,getCalls:()=>calls};
}

test("accepts enrolled Ed25519 packet and rejects altered data",()=>{
  const f=fixture();
  assert.equal(verifyDevicePacket(f.packet,f.registry).sequence,1n);
  assert.throws(()=>verifyDevicePacket({...f.packet,payload:{temperatureC:99}},f.registry),
                /signature/);
  assert.throws(()=>verifyDevicePacket(f.packet,{}),/not authorized/);
});

test("Privi-only configuration rejects known foreign networks and public HTTP",()=>{
  const config=configuration();
  assert.equal(validateNetworkConfig(config).chainId,262144);
  assert.throws(()=>validateNetworkConfig({...config,chainId:56}),/Third-party/);
  assert.throws(()=>validateNetworkConfig({...config,chainId:8453}),/Third-party/);
  assert.throws(()=>validateNetworkConfig({...config,rpcUrl:"http://example.org:8545"}),/loopback/);
  assert.throws(()=>validateNetworkConfig({...config,genesisHash:"0x00"}),/genesis/);
  assert.throws(()=>validateNetworkConfig({...config,mode:"production"}),/Production IoT submission blocked/);
  assert.throws(()=>validateNetworkConfig({...config,chainId:99999}),/Only Privi disposable/);
  assert.throws(()=>validateNetworkConfig({...config,network:"ethereum"}),/Only native Privi/);
  assert.throws(()=>validateNetworkConfig({...config,settlementChain:"base"}),/Only native Privi/);
  assert.throws(()=>validateNetworkConfig({...config,bridgeMode:"enabled"}),/forbids automatic/);
  assert.throws(()=>validateNetworkConfig({...config,pairingMode:"enabled"}),/forbids automatic/);
});

test("refuses incorrect Privi genesis and wrong on-chain runtime",async()=>{
  const config=configuration(), f=fixture(), m=mocks(f,config);
  await assertPriviChain(m.provider,config);
  await assert.rejects(()=>assertPriviChain(m.provider,{...config,genesisHash:"0x"+"b".repeat(64)}),/genesis/);
  await assert.rejects(()=>assertPriviChain(m.provider,{...config,contractCodeSha256:"0x"+"b".repeat(64)}),/runtime/);
});

test("confirmed IoT event returns Privi tx hash and metadata, never mints",async()=>{
  const f=fixture(),config=configuration(),m=mocks(f,config);
  const result=await submitEvent(f.packet,{registry:f.registry,config,...m});
  assert.equal(result.transactionHash,"0x"+"9".repeat(64));
  assert.equal(result.chainId,262144);
  assert.equal(result.confirmations,2);
  assert.equal(result.payloadHash,packetDigest(f.packet).payloadHash);
  assert.equal(m.getCalls(),1);
});

test("rejects wrong chain before any transaction",async()=>{
  const f=fixture(),config=configuration(),m=mocks(f,config);
  m.provider.send=async method=>method==="eth_chainId"?"0x38":null;
  await assert.rejects(()=>submitEvent(f.packet,{registry:f.registry,config,...m}),/not the configured Privi/);
  assert.equal(m.getCalls(),0);
});

test("rejects replays, wrong gateway and a different provider",async()=>{
  const f=fixture(),config=configuration(),m=mocks(f,config);
  m.contract.devices=async()=>({
    gateway:m.wallet.address,signingKeyHash:f.signingKeyHash,lastSequence:1n,
    enabled:true,enrolled:true
  });
  await assert.rejects(()=>submitEvent(f.packet,{registry:f.registry,config,...m}),/sequence/);
  assert.equal(m.getCalls(),0);
  m.contract.devices=async()=>({
    gateway:"0x"+"4".repeat(40),signingKeyHash:f.signingKeyHash,lastSequence:0n,
    enabled:true,enrolled:true
  });
  await assert.rejects(()=>submitEvent(f.packet,{registry:f.registry,config,...m}),/Gateway/);
  assert.equal(m.getCalls(),0);
  const wrongWallet={...m.wallet,provider:{}};
  await assert.rejects(()=>submitEvent(f.packet,{registry:f.registry,config,
    provider:m.provider,wallet:wrongWallet,contract:m.contract}),/pinned Privi provider/);
  assert.equal(m.getCalls(),0);
});

test("revoked or unknown Privi developers are rejected without submitting",async()=>{
  const f=fixture(),config=configuration(),m=mocks(f,config);
  m.contract.developers=async()=>({registered:false,enabled:false});
  await assert.rejects(()=>submitEvent(f.packet,{registry:f.registry,config,...m}),/Privi developer registration/);
  assert.equal(m.getCalls(),0);
  m.contract.developers=async()=>({registered:true,enabled:false});
  await assert.rejects(()=>submitEvent(f.packet,{registry:f.registry,config,...m}),/Privi developer registration/);
  assert.equal(m.getCalls(),0);
});

test("missing matching mined receipt is rejected",async()=>{
  const f=fixture(),config=configuration(),m=mocks(f,config);
  m.contract.interface.parseLog=()=>{throw Error("no logs");};
  await assert.rejects(()=>submitEvent(f.packet,{registry:f.registry,config,...m}),/missing matching/i);
  assert.equal(m.getCalls(),1);
});
