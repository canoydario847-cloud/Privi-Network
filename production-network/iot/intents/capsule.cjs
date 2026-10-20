"use strict";
/*
 * Privi Intent Capsules v1 — non-Turing-complete, deterministic declarative
 * authorization for ONE developer-chain IoT event. EIP-191 company-admin
 * consent, position specificity, payload predicates, on-chain admin epoch,
 * lifetime and worst-case gas-cost ceilings.
 *
 * This is a GATEWAY-SIDE DEVELOPMENT POLICY, not consensus-native PoP,
 * not an executable on-chain smart contract, not an escrow or token.
 * The real on-chain transaction is still checked by PriviIoTLedger.
 */
const {sha, canonical} = require("../gateway/core.cjs");
const ADDRESS=/^0x[0-9a-fA-F]{40}$/;
const H32=/^0x[0-9a-fA-F]{64}$/;
const DECIMAL=/^(?:0|[1-9][0-9]{0,25})$/;
const TYPE="privi.iot.record";
const DOMAIN="Privi/IntentCapsule/DEVELOPMENT/v1";
const ALLOWED_FIELDS=new Set(["version","type","chainId","genesisHash","contractAddress",
  "companyIdHash","deviceIdHash","eventHash","popStampHash","gateway",
  "companyEpoch","notBefore","expiresAt","nonce","maxGasPriceWei","maxGasLimit",
  "maxTotalWei","predicates"]);
const ALLOWED_PREDICATE_FIELDS=new Set(["field","min","max"]);
function ensure(value,message){if(!value)throw Error(message)}
const eq=(a,b)=>typeof a==="string"&&typeof b==="string"&&a.toLowerCase()===b.toLowerCase();
function canonicalCapsule(capsule){
  ensure(capsule && typeof capsule==="object" && !Array.isArray(capsule) &&
    Object.getPrototypeOf(capsule)===Object.prototype,"Intent Capsule must be a plain object");
  for(const key of Object.keys(capsule))
    ensure(ALLOWED_FIELDS.has(key),"Unknown Intent Capsule field: "+key);
  ensure(Object.keys(capsule).length===ALLOWED_FIELDS.size,
    "Intent Capsule requires every explicit security field");
  ensure(capsule.version===1 && capsule.type===TYPE,"Unsupported Privi Intent Capsule version/type");
  ensure(Number.isSafeInteger(capsule.chainId)&&capsule.chainId===262144,
    "Intent Capsule accepts only Privi disposable developer chain");
  for(const name of ["genesisHash","companyIdHash","deviceIdHash","eventHash","popStampHash","nonce"])
    ensure(typeof capsule[name]==="string"&&H32.test(capsule[name]),
      "Invalid Intent Capsule "+name);
  ensure(capsule.nonce.toLowerCase()!=="0x"+"0".repeat(64),"Intent nonce must not be zero");
  for(const name of ["contractAddress","gateway"])
    ensure(typeof capsule[name]==="string"&&ADDRESS.test(capsule[name]),
      "Invalid Intent Capsule "+name);
  ensure(Number.isSafeInteger(capsule.companyEpoch)&&capsule.companyEpoch>0 &&
    capsule.companyEpoch<=1000000,"Intent Capsule company epoch invalid");
  ensure(Number.isSafeInteger(capsule.notBefore)&&capsule.notBefore>0 &&
    Number.isSafeInteger(capsule.expiresAt)&&capsule.expiresAt>capsule.notBefore &&
    capsule.expiresAt-capsule.notBefore<=3600,"Intent Capsule lifetime exceeds 60 minutes");
  ensure(Number.isSafeInteger(capsule.maxGasLimit)&&capsule.maxGasLimit>=50000 &&
    capsule.maxGasLimit<=1000000,"Intent Capsule gas limit invalid");
  for(const name of ["maxGasPriceWei","maxTotalWei"])
    ensure(typeof capsule[name]==="string"&&DECIMAL.test(capsule[name])&&
      BigInt(capsule[name])>0n, "Invalid Intent Capsule "+name);
  ensure(BigInt(capsule.maxGasPriceWei)*BigInt(capsule.maxGasLimit)<=
    BigInt(capsule.maxTotalWei),"Intent Capsule worst-case gas exceeds company budget");
  ensure(Array.isArray(capsule.predicates)&&capsule.predicates.length>=1&&
    capsule.predicates.length<=8,"Intent Capsule needs 1..8 safe predicates");
  const names=new Set();
  for(const p of capsule.predicates){
    ensure(p&&typeof p==="object"&&!Array.isArray(p)&&Object.getPrototypeOf(p)===Object.prototype,
      "Predicate must be a plain object");
    ensure(Object.keys(p).length===3 &&
      Object.keys(p).every(x=>ALLOWED_PREDICATE_FIELDS.has(x)),
      "Unknown or missing Intent Capsule predicate field");
    ensure(typeof p.field==="string" && /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(p.field) &&
      !names.has(p.field),"Predicate field invalid/duplicate");
    names.add(p.field);
    ensure(Number.isSafeInteger(p.min)&&Number.isSafeInteger(p.max)&&p.min<=p.max,
      "Predicate range must use safe integers");
  }
  const serialized=canonical(capsule);
  ensure(Buffer.byteLength(serialized,"utf8")<=4096,"Intent Capsule is too large");
  return serialized;
}
function intentMessage(capsule){
  return DOMAIN+"\nRESEARCH ONLY - NOT FINANCIAL MAINNET\n"+
    canonicalCapsule(capsule);
}
function issuerBoundDigest(capsule){
  return sha(Buffer.from(intentMessage(capsule),"utf8"));
}
function validatePredicate(packet,p){
  ensure(packet&&packet.payload&&typeof packet.payload==="object"&&!Array.isArray(packet.payload),
    "Invalid IoT payload for intent predicates");
  ensure(Object.hasOwn(packet.payload,p.field),"Intent Capsule payload predicate is absent");
  const val=packet.payload[p.field];
  ensure(Number.isSafeInteger(val)&&val>=p.min&&val<=p.max,
    "Intent Capsule payload predicate out of authorized range");
}
function read(row,name,index){return row?.[name]!==undefined?row[name]:row?.[index]}

/** Returns transaction overrides only after genuine on-chain admin signer check. */
async function verifyIntentCapsule({capsule,signature,event,packet,config,wallet,
   contract,provider,ethers}){
  const text=intentMessage(capsule);
  ensure(ethers && typeof ethers.verifyMessage==="function",
    "EIP-191 verifier is required");
  ensure(typeof signature==="string"&&/^0x[0-9a-fA-F]{130}$/.test(signature),
    "Intent Capsule EIP-191 company signature required");
  ensure(config.mode==="development"&&config.chainId===262144,
    "Intent Capsule financial/mainnet automation prohibited");
  ensure(capsule.chainId===config.chainId&&eq(capsule.genesisHash,config.genesisHash)&&
    eq(capsule.contractAddress,config.contractAddress),
    "Intent Capsule foreign chain, genesis or contract refused");
  ensure(eq(capsule.gateway,wallet.address) &&
    eq(capsule.companyIdHash,event.companyIdHash) &&
    eq(capsule.deviceIdHash,event.deviceIdHash) &&
    eq(capsule.eventHash,event.eventHash) &&
    eq(capsule.popStampHash,event.popStampHash),
    "Intent Capsule does not authorize this exact signed PoP event");
  for(const predicate of capsule.predicates) validatePredicate(packet,predicate);
  const nowBlock=await provider.send("eth_getBlockByNumber",["latest",false]);
  ensure(nowBlock&&typeof nowBlock.timestamp==="string"&&/^0x[0-9a-f]+$/i.test(nowBlock.timestamp),
    "Pinned Privi block timestamp required");
  const now=Number(BigInt(nowBlock.timestamp));
  ensure(Number.isSafeInteger(now)&&now>=capsule.notBefore&&now<=capsule.expiresAt,
    "Intent Capsule not active or already expired");
  const company=await contract.companies(event.companyIdHash);
  ensure(read(company,"registered",1)===true&&read(company,"enabled",2)===true,
    "Intent company not registered or suspended");
  const epoch=await contract.companyGatewayEpoch(event.companyIdHash);
  ensure(BigInt(epoch)===BigInt(capsule.companyEpoch),
    "Intent Capsule revoked by company administrator epoch change");
  ensure(await contract.companyGateways(event.companyIdHash,wallet.address)===true,
    "Intent Capsule gateway not approved by company");
  let signer;
  try{signer=ethers.verifyMessage(text,signature)}
  catch{throw Error("Invalid Intent Capsule company signature")}
  ensure(eq(signer,read(company,"administrator",0)),
    "Intent Capsule signature is not from the current company administrator");
  return Object.freeze({
    capsuleDigest:issuerBoundDigest(capsule),
    issuer:signer,
    overrides:Object.freeze({
      gasPrice:BigInt(capsule.maxGasPriceWei),
      gasLimit:BigInt(capsule.maxGasLimit)
    }),
    worstCaseFeeWei:(BigInt(capsule.maxGasPriceWei)*BigInt(capsule.maxGasLimit)).toString(),
    researchOnly:true,financialMainnet:false,automaticTokenTransfer:false
  });
}
module.exports={DOMAIN,TYPE,canonicalCapsule,intentMessage,issuerBoundDigest,verifyIntentCapsule};
