"use strict";
/*
 * READ-ONLY, DEV-ONLY Privi Point of Position validator-position evidence.
 * This verifies actual IoTRecorded receipts from the *disposable upstream*
 * Cosmos EVM test ledger. It DOES NOT prove native PoP consensus, owner
 * authorization, real fault-domain independence or financial mainnet.
 *
 * Pinned developer RPC, genesis, EVM chain ID, deployed contract code hash,
 * canonical receipt, mined block, position stamp, Ed25519 device key and
 * Privi World Corp device enrollment must all match. Synthetic hashes alone
 * cannot pass. No private keys are used here.
 */
const crypto = require("node:crypto");
const {
  parseRegistry,OWNER_EVM_WALLET,OWNER_OPERATOR_ID,OWNER_COMPANY_ID
} = require("./engine.cjs");
const {assertPriviChain, sha} = require("../../iot/gateway/core.cjs");

const HEX32=/^0x[0-9a-fA-F]{64}$/;
const ZONE="VALIDATOR/AUTH";
const EVENT_TYPE="validator_position";
function check(ok,why) { if(!ok)throw Error(why); }
const eq=(a,b)=>typeof a==="string" && typeof b==="string" &&
  a.toLowerCase()===b.toLowerCase();
const hashText=x=>sha(Buffer.from(x,"utf8"));
function blockInt(raw,label){
  check(typeof raw==="string" && /^0x[0-9a-f]+$/i.test(raw),
        "Invalid "+label);
  return BigInt(raw);
}

async function verifyOne({provider,config,contract,validator,transactionHash,ethers}) {
  check(typeof transactionHash==="string" && HEX32.test(transactionHash),
        "PoP anchor needs canonical transaction hash");
  const receipt=await provider.send("eth_getTransactionReceipt",[transactionHash]);
  check(receipt && eq(receipt.transactionHash,transactionHash) &&
        blockInt(receipt.status,"PoP transaction status")===1n,
        "PoP native test-ledger transaction not confirmed successful");
  check(HEX32.test(receipt.blockHash||"") &&
        blockInt(receipt.blockNumber,"PoP block number")>0n,
        "PoP anchor block hash and height required");
  const latest=blockInt(await provider.send("eth_blockNumber",[]),
                        "Privi head height");
  const height=blockInt(receipt.blockNumber,"PoP anchor height");
  check(latest>=height+BigInt(config.confirmations-1),
        "PoP anchor has fewer than required developer-chain confirmations");
  const block=await provider.send("eth_getBlockByNumber",
                                    [receipt.blockNumber,false]);
  check(block && eq(block.hash,receipt.blockHash) &&
        blockInt(block.number,"PoP canonical block number")===height,
        "PoP event receipt is not on the current canonical test ledger");
  check(eq(validator.anchorBlockHash,receipt.blockHash),
        "Research validator admission is not bound to the observed receipt block");
  check(contract && contract.interface &&
        typeof contract.interface.parseLog==="function" &&
        typeof contract.devices==="function",
        "Pinned Privi IoT contract interface required");
  check(typeof ethers?.getAddress==="function","Pinned ethers v6 required");
  check(eq(await contract.getAddress(),config.contractAddress),
        "PoP event contract target differs from pinned deployment");
  const stamp=validator.companyId+":VALIDATOR/AUTH:"+
    String(validator.positionSequence).padStart(6,"0");
  const expectedStamp="PoP:"+stamp;
  const expectedHash=hashText(expectedStamp);
  check(eq(expectedHash,validator.positionHash),
        "Privi research validator PoP stamp hash is incorrect");
  const zoneHash=hashText(ZONE);
  const companyHash=hashText(OWNER_COMPANY_ID);
  const eventTypeHash=hashText(EVENT_TYPE);
  const der=Buffer.from(validator.keySpkiBase64,"base64");
  check(der.toString("base64")===validator.keySpkiBase64,
        "Validator Ed25519 public key DER is malformed");
  const signingKeyHash=sha(der);
  let matched=false, matchedDeviceId;
  for(const log of receipt.logs||[]) {
    if(!eq(log.address,config.contractAddress))continue;
    let parsed;
    try {parsed=contract.interface.parseLog(log);}catch(_){continue}
    if(!parsed||parsed.name!=="IoTRecorded")continue;
    const args=parsed.args;
    if(!eq(args.popStampHash??args[7],expectedHash) ||
       !eq(args.popZoneHash??args[8],zoneHash) ||
       !eq(args.eventTypeHash??args[4],eventTypeHash) ||
       BigInt(args.positionSequence??args[9])!==BigInt(validator.positionSequence))
       continue;
    const deviceIdHash=String(args.deviceIdHash??args[0]);
    const device=await contract.devices(deviceIdHash);
    if (!eq(device.companyIdHash??device[5],companyHash) ||
        !eq(device.signingKeyHash??device[1],signingKeyHash))continue;
    check(!matched,"Ambiguous duplicated validator position logs");
    matched=true;matchedDeviceId=deviceIdHash;
  }
  check(matched,"No actual Privi ledger event binds validator Ed25519 key and PoP position");
  return Object.freeze({
    validatorId:validator.id,
    transactionHash,anchorBlockHash:receipt.blockHash,
    anchoredHeight:height.toString(),deviceIdHash:matchedDeviceId,
    positionHash:validator.positionHash,
    testLedgerOnly:true, productionConsensus:false
  });
}

async function verifyCandidatePositionAnchors({
  provider, config, contract, registry, governanceKey, proofs, ethers
}) {
  await assertPriviChain(provider,config); // strict dev-only chain/genesis/code pin
  const committee=parseRegistry(registry,governanceKey); // attested research admission
  check(committee.ownerWallet===OWNER_EVM_WALLET &&
        committee.operatorId===OWNER_OPERATOR_ID,
        "Wrong Privi research governance declaration");
  check(Array.isArray(proofs) && proofs.length===committee.validators.length,
        "Every research validator must have a distinct test-ledger anchor proof");
  const proofById=new Map();
  for(const proof of proofs){
    check(proof && typeof proof==="object" &&
          typeof proof.validatorId==="string" &&
          HEX32.test(proof.transactionHash||"") &&
          !proofById.has(proof.validatorId) &&
          committee.byId.has(proof.validatorId),
          "Missing, duplicate or extraneous PoP validator anchor");
    proofById.set(proof.validatorId,proof);
  }
  const evidence=[];
  const seenTx=new Set();
  for(const v of registry.validators){
    const proof=proofById.get(v.id);
    check(proof,"Unanchored Privi validator");
    const tx=proof.transactionHash.toLowerCase();
    check(!seenTx.has(tx),"One transaction cannot falsely stand for two validator anchors");
    seenTx.add(tx);
    evidence.push(await verifyOne({
      provider,config,contract,validator:v,transactionHash:proof.transactionHash,ethers
    }));
  }
  return Object.freeze({
    researchOnly:true,
    verifiedTestLedgerAnchors:evidence.length,
    chainId:config.chainId,
    testLedgerGenesisHash:config.genesisHash,
    committeeHash:hashText(JSON.stringify(evidence.map(e=>[e.validatorId,e.positionHash,
      e.transactionHash,e.anchorBlockHash]).sort((a,b)=>a[0].localeCompare(b[0])))),
    evidence,
    nativePoPConsensus:false,
    founderSignatureVerified:false,
    productionMainnet:false
  });
}
module.exports={verifyCandidatePositionAnchors,ZONE,EVENT_TYPE};