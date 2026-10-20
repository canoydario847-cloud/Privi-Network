"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const crypto=require("node:crypto");
const {
  hash,signedMessage,positionStamp,TRUSTED_MODE,
  OWNER_EVM_WALLET,OWNER_OPERATOR_ID,OWNER_COMPANY_ID
}=require("./engine.cjs");
const {verifyCandidatePositionAnchors}=require("./onchain_anchor_verifier.cjs");
const {sha}=require("../../iot/gateway/core.cjs");

// Mocked RPC tests for fail-closed behavior. The separate four-validator
// integration CI checks actual mined receipts, not these fake fixtures.
const H=s=>sha(Buffer.from(s,"utf8"));
function fixture(){
  const gov=crypto.generateKeyPairSync("ed25519");
  const govPub=gov.publicKey.export({type:"spki",format:"der"}).toString("base64");
  const chainId="privi-pop-research-receipts",genesisHash="0x"+"a".repeat(64),epoch=1;
  const testLedgerGenesis="0x"+"b".repeat(64);
  const address="0x"+"1".repeat(40);
  const code="0x6000600055";
  const config={
    mode:"development",network:"privi-native",settlementChain:"privi",
    bridgeMode:"disabled",pairingMode:"disabled",rpcUrl:"http://127.0.0.1:8545",
    chainId:262144,genesisHash:testLedgerGenesis,
    contractAddress:address,contractCodeSha256:sha(Buffer.from(code.slice(2),"hex")),
    confirmations:2
  };
  const vals=[],proofs=[],receipts=new Map(),devices=new Map();
  const anchorBlockHash="0x"+"d".repeat(64);
  for(let i=0;i<4;i++){
    const pair=crypto.generateKeyPairSync("ed25519");
    const der=pair.publicKey.export({type:"spki",format:"der"});
    const id=hash(der),positionSequence=i+1;
    const positionHash=H(positionStamp(OWNER_COMPANY_ID,positionSequence));
    const faultDomain="claimed-host-"+i+".example";
    const fields=[
      chainId,genesisHash,epoch,OWNER_EVM_WALLET,OWNER_OPERATOR_ID,
      faultDomain,OWNER_COMPANY_ID,positionSequence,id,anchorBlockHash
    ];
    vals.push({
      id,keySpkiBase64:der.toString("base64"),operatorId:OWNER_OPERATOR_ID,
      companyId:OWNER_COMPANY_ID,faultDomain,positionSequence,positionHash,
      anchorBlockHash,
      admissionSignature:crypto.sign(null,signedMessage("admit",fields),gov.privateKey)
        .toString("base64")
    });
    const deviceIdHash=H("validator-device-"+i);
    devices.set(deviceIdHash,{
      companyIdHash:H(OWNER_COMPANY_ID),signingKeyHash:sha(der)
    });
    const transactionHash=H("tx-"+i);
    const args={
      deviceIdHash,sequence:1n,eventHash:H("event-"+i),
      payloadHash:H("payload-"+i),eventTypeHash:H("validator_position"),
      signatureHash:H("signature-"+i),observedAt:1760912345n,
      popStampHash:positionHash,popZoneHash:H("VALIDATOR/AUTH"),
      positionSequence:BigInt(positionSequence)
    };
    receipts.set(transactionHash,{
      transactionHash,blockHash:anchorBlockHash,blockNumber:"0x5",status:"0x1",
      logs:[{address,parsed:{name:"IoTRecorded",args}}]
    });
    proofs.push({validatorId:id,transactionHash});
  }
  const registry={
    chainId,genesisHash,epoch,mode:TRUSTED_MODE,
    ownerWallet:OWNER_EVM_WALLET,operatorId:OWNER_OPERATOR_ID,
    validators:vals
  };
  let rpcHead="0x10",rpcGenesis=testLedgerGenesis,rpcCode=code;
  const provider={
    async send(method,args){
      if(method==="eth_chainId")return "0x40000";
      if(method==="eth_getBlockByNumber"){
        if(args[0]==="0x0")return {hash:rpcGenesis};
        return {hash:anchorBlockHash,number:"0x5",timestamp:"0x1"};
      }
      if(method==="eth_getCode")return rpcCode;
      if(method==="eth_getTransactionReceipt")return receipts.get(args[0])||null;
      if(method==="eth_blockNumber")return rpcHead;
      throw Error("unexpected RPC "+method);
    }
  };
  const contract={
    interface:{parseLog:log=>log.parsed},
    getAddress:async()=>address,
    devices:async id=>devices.get(id)
  };
  const args={
    provider,config,contract,registry,governanceKey:govPub,proofs,
    ethers:{getAddress:address=>address}
  };
  return {
    args,receipts,devices,config,registry,proofs,
    setHead:x=>{rpcHead=x},
    setGenesis:x=>{rpcGenesis=x},
    setCode:x=>{rpcCode=x}
  };
}
test("four individually signed PoP admissions tie to four separate receipt transactions",async()=>{
  const f=fixture();
  const result=await verifyCandidatePositionAnchors(f.args);
  assert.equal(result.verifiedTestLedgerAnchors,4);
  assert.equal(result.evidence.length,4);
  assert.equal(result.nativePoPConsensus,false);
  assert.equal(result.founderSignatureVerified,false);
  assert.equal(result.productionMainnet,false);
});
test("reject fictitious, failed, duplicate or reused transactions",async()=>{
  const f=fixture();
  const bogus=f.proofs.map(x=>({...x}));
  bogus[0].transactionHash=H("does-not-exist");
  await assert.rejects(verifyCandidatePositionAnchors({...f.args,proofs:bogus}),/not confirmed/);
  const receipt=f.receipts.get(f.proofs[0].transactionHash);
  receipt.status="0x0";
  await assert.rejects(verifyCandidatePositionAnchors(f.args),/not confirmed/);
  receipt.status="0x1";
  const reused=f.proofs.map(x=>({...x}));
  reused[1].transactionHash=reused[0].transactionHash;
  await assert.rejects(verifyCandidatePositionAnchors({...f.args,proofs:reused}),
                       /One transaction cannot falsely stand/);
  await assert.rejects(verifyCandidatePositionAnchors({
    ...f.args,proofs:f.proofs.slice(1)}),/Every research validator/);
});
test("reject altered position stamp, event type, enrolled Ed25519 key or native company",async()=>{
  const f=fixture(),receipt=f.receipts.get(f.proofs[0].transactionHash);
  const args=receipt.logs[0].parsed.args;
  args.popStampHash=H("forged");
  await assert.rejects(verifyCandidatePositionAnchors(f.args),/No actual Privi ledger event/);
  args.popStampHash=f.registry.validators[0].positionHash;
  args.eventTypeHash=H("temperature");
  await assert.rejects(verifyCandidatePositionAnchors(f.args),/No actual Privi ledger event/);
  args.eventTypeHash=H("validator_position");
  const device=f.devices.get(args.deviceIdHash);
  device.signingKeyHash=H("another signer");
  await assert.rejects(verifyCandidatePositionAnchors(f.args),/No actual Privi ledger event/);
  device.signingKeyHash=sha(Buffer.from(f.registry.validators[0].keySpkiBase64,"base64"));
  device.companyIdHash=H("foreign-company");
  await assert.rejects(verifyCandidatePositionAnchors(f.args),/No actual Privi ledger event/);
});
test("reject foreign RPC genesis, different on-chain code and unconfirmed blocks",async()=>{
  const f=fixture();
  f.setGenesis("0x"+"e".repeat(64));
  await assert.rejects(verifyCandidatePositionAnchors(f.args),/genesis/);
  f.setGenesis(f.config.genesisHash);
  f.setCode("0x60006000");
  await assert.rejects(verifyCandidatePositionAnchors(f.args),/code differs/);
  f.setCode("0x6000600055");
  f.setHead("0x5");
  await assert.rejects(verifyCandidatePositionAnchors(f.args),/fewer than required/);
});
test("reject tampered receipts and fake validator admission despite syntactically correct hashes",async()=>{
  const f=fixture(),receipt=f.receipts.get(f.proofs[0].transactionHash);
  receipt.blockHash="0x"+"e".repeat(64);
  await assert.rejects(verifyCandidatePositionAnchors(f.args),/not on the current canonical/);
  receipt.blockHash="0x"+"d".repeat(64);
  const forged=structuredClone(f.registry);
  forged.validators[0].anchorBlockHash="0x"+"f".repeat(64);
  await assert.rejects(verifyCandidatePositionAnchors({...f.args,registry:forged}),
    /admission signature/);
});
