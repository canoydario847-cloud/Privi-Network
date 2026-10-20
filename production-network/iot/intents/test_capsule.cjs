"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const {packetDigest,sha}=require("../gateway/core.cjs");
const {DOMAIN,canonicalCapsule,intentMessage,issuerBoundDigest,verifyIntentCapsule}=
  require("./capsule.cjs");
const p=process.env.PRIVI_CAPSULE_ETHERS_PATH;
if(!p||!p.includes("privi-intent-ethers"))
  throw Error("Tests require pinned disposable ethers@6.15.0 module");
const ethers=require(p);
const ADMIN=ethers.Wallet.createRandom();
const FOREIGN=ethers.Wallet.createRandom();
const ADDRESS="0x"+"1".repeat(40),GATEWAY="0x"+"3".repeat(40);
const GENESIS="0x"+"a".repeat(64);
function fixture(){
 const packet={version:3,companyId:"PRIVI_TEST_CO",deviceId:"sensor-01",
  sequence:1,positionSequence:1,observedAt:1760912345,
  popZone:"GRID/READINGS",eventType:"temperature",
  payload:{temperatureCentidegrees:2250,humidityPercent:43}};
 const event=packetDigest(packet);
 const capsule={
  version:1,type:"privi.iot.record",chainId:262144,genesisHash:GENESIS,
  contractAddress:ADDRESS,companyIdHash:event.companyIdHash,
  deviceIdHash:event.deviceIdHash,eventHash:event.eventHash,
  popStampHash:event.popStampHash,gateway:GATEWAY,companyEpoch:2,
  nonce:"0x"+"f".repeat(64),notBefore:1800000000-10,
  expiresAt:1800000000+300,
  maxGasPriceWei:"10000000000",maxGasLimit:450000,
  maxTotalWei:"4500000000000000",
  predicates:[{field:"temperatureCentidegrees",min:2200,max:2400}]
 };
 const wallet={address:GATEWAY};
 const config={mode:"development",chainId:262144,genesisHash:GENESIS,contractAddress:ADDRESS};
 const provider={send:async(m)=> {
  if(m!=="eth_getBlockByNumber")throw Error("unexpected method");
  return {timestamp:"0x"+(1800000000).toString(16)};
 }};
 let administrator=ADMIN.address,epoch=2n,registered=true,enabled=true,approved=true;
 const contract={
  companies:async()=>({administrator,registered,enabled}),
  companyGatewayEpoch:async()=>epoch,
  companyGateways:async()=>approved
 };
 return {packet,event,capsule,wallet,config,provider,contract,ethers,
  mutate:{
   epoch:x=>{epoch=x},admin:x=>{administrator=x},
   registered:x=>{registered=x},enabled:x=>{enabled=x},approved:x=>{approved=x}
  }};
}
async function run(f,who=ADMIN){
 const signature=await who.signMessage(intentMessage(f.capsule));
 return verifyIntentCapsule({...f,signature});
}
test("independent company administrator EIP-191 authorizes one Privi-only IoT action",async()=>{
 const f=fixture();
 assert.ok(intentMessage(f.capsule).startsWith(DOMAIN+"\n"));
 assert.equal(issuerBoundDigest(f.capsule),sha(Buffer.from(intentMessage(f.capsule),"utf8")));
 const result=await run(f);
 assert.equal(result.issuer,ADMIN.address);
 assert.equal(result.researchOnly,true);
 assert.equal(result.financialMainnet,false);
 assert.equal(result.automaticTokenTransfer,false);
 assert.equal(result.overrides.gasPrice,10000000000n);
 assert.equal(result.overrides.gasLimit,450000n);
 assert.equal(result.worstCaseFeeWei,"4500000000000000");
});
test("forged, malformed, absent company signer fails closed",async()=>{
 const f=fixture();
 await assert.rejects(run(f,FOREIGN),/current company administrator/);
 await assert.rejects(verifyIntentCapsule({...f,signature:"0x12"}),/EIP-191/);
 await assert.rejects(verifyIntentCapsule({...f,signature:undefined}),/EIP-191/);
 const signature=await ADMIN.signMessage(intentMessage(f.capsule));
 f.capsule.maxGasLimit=455000;
 f.capsule.maxTotalWei="4550000000000000";
 await assert.rejects(verifyIntentCapsule({...f,signature}),/current company administrator/);
});
test("company epoch rotation and company suspension instantly invalidate capsules",async()=>{
 const f=fixture();
 f.mutate.epoch(3n);
 await assert.rejects(run(f),/epoch change/);
 f.mutate.epoch(2n);f.mutate.admin(FOREIGN.address);
 await assert.rejects(run(f),/current company administrator/);
 f.mutate.admin(ADMIN.address);f.mutate.approved(false);
 await assert.rejects(run(f),/not approved/);
 f.mutate.approved(true);f.mutate.enabled(false);
 await assert.rejects(run(f),/not registered or suspended/);
 f.mutate.enabled(true);f.mutate.registered(false);
 await assert.rejects(run(f),/not registered or suspended/);
});
test("event hash, position, device, company, gateway, genesis, address and chain pinned",async()=>{
 const columns=[
   ["eventHash","0x"+"c".repeat(64)],
   ["popStampHash","0x"+"d".repeat(64)],
   ["deviceIdHash","0x"+"e".repeat(64)],
   ["companyIdHash","0x"+"9".repeat(64)],
   ["gateway","0x"+"a".repeat(40)],
   ["genesisHash","0x"+"b".repeat(64)],
   ["contractAddress","0x"+"9".repeat(40)],
   ["chainId",56]
 ];
 for (const [key,value] of columns){
  const f=fixture();f.capsule[key]=value;
  await assert.rejects(run(f),/foreign chain|does not authorize|developer chain/);
 }
});
test("rule predicates, validity and fee ceilings fail before signing a transaction",async()=>{
 const mutators=[
  f=>{f.packet.payload.temperatureCentidegrees=2700},
  f=>{delete f.packet.payload.temperatureCentidegrees},
  f=>{f.capsule.expiresAt=1799999999},
  f=>{f.capsule.notBefore=1800000100;f.capsule.expiresAt=1800000200},
  f=>{f.capsule.maxTotalWei="1000"},
  f=>{f.capsule.maxGasLimit=2000000},
  f=>{f.capsule.maxGasPriceWei="-1"},
  f=>{f.capsule.predicates=[]},
  f=>{f.capsule.predicates=[{field:"temperatureCentidegrees",min:2200,max:2400},
                            {field:"temperatureCentidegrees",min:2000,max:2400}]}
 ];
 for (const makeBad of mutators){
  const f=fixture();makeBad(f);
  await assert.rejects(run(f),/predicate|not active|expired|gas|budget|1..8|lifetime|maxGasPriceWei/i);
 }
});
test("deny unknown fields, dynamic JS keys, zero nonce, float conditions and extension attack",()=>{
 for(const makeBad of [
  f=>{f.capsule.outsideLedger="ethereum"},
  f=>{f.capsule.nonce="0x"+"0".repeat(64)},
  f=>{f.capsule.predicates[0].min=0.5},
  f=>{f.capsule.predicates[0].callback="import('attacker')"},
  f=>{f.capsule.predicates[0].field="__proto__"}
 ]){
  const f=fixture();makeBad(f);
  assert.throws(()=>canonicalCapsule(f.capsule),/Unknown|nonce|safe integer|predicate|Predicate/);
 }
});
