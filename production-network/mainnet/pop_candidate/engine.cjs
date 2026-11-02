"use strict";
/*
 * Privi PoP finality RESEARCH PROTOTYPE ONLY.
 *
 * This is NOT part of Cosmos EVM / CometBFT / ABCI validator state and
 * does NOT install PoP consensus, select live validators, create native PRVI,
 * mint coins, bridge networks, or activate public mainnet.
 *
 * Explicit governance-attested position admission + authenticated proposal
 * / commit certificate evaluation. Shares terminology with Canoy's Point of
 * Position paper but offers NEW, unreviewed candidate BFT mechanics.
 *
 * Security limits: a single governance root admits operators; fault-domain
 * claims and PoP position meaning require independent external verification;
 * proposal availability, reliable broadcast, safety across validator restarts,
 * network scheduling, multi-round locks and leader-change proofs are absent.
 * NEVER use this as real finality without a formal protocol and auditing.
 */
const crypto = require("node:crypto");

const HEX = /^0x[0-9a-f]{64}$/;
const ORGANIZATION = /^[A-Z0-9_-]{2,32}$/;
const DOMAIN = /^[a-z0-9][a-z0-9._-]{1,63}$/;
const CHAIN = /^privi-pop-research-[a-z0-9-]{1,48}$/;
const PREFIX = "Privi/PoP/Research/2026/v1";
const TRUSTED_MODE = "attested-position-research-not-live-consensus";
// Proof objects must originate from validated governance admissions, not a
// caller-supplied object with an arbitrary reduced signature threshold.
const validatedCommittees = new WeakSet();
// The admitted signer map is mutable despite the frozen committee wrapper.
// Pin native Map accessors so per-instance get/has/size overrides cannot
// redirect research signature verification to attacker-supplied keys.
const nativeMapGet = Map.prototype.get;
const nativeMapSet = Map.prototype.set;
const nativeMapHas = Map.prototype.has;
const nativeMapSize = Object.getOwnPropertyDescriptor(Map.prototype,"size").get;
function check(ok, why) { if (!ok) throw Error(why); }
function hash(data) {
  return "0x" + crypto.createHash("sha256").update(data).digest("hex");
}
function publicKey(derB64) {
  check(typeof derB64 === "string" && /^[a-zA-Z0-9+/]+={0,2}$/.test(derB64),
        "Missing canonical Ed25519 public key");
  const buf = Buffer.from(derB64, "base64");
  check(buf.length >= 32 && buf.length <= 128 && buf.toString("base64") === derB64,
        "Invalid Ed25519 public key encoding");
  const key = crypto.createPublicKey({key:buf,format:"der",type:"spki"});
  check(key.asymmetricKeyType === "ed25519", "PoP requires Ed25519 position signers");
  // Node/OpenSSL may accept trailing bytes after a valid SPKI DER object.
  // Hashing those bytes would assign distinct validator IDs to ONE signing key,
  // allowing a single Ed25519 key to masquerade as multiple research voters.
  check(key.export({type:"spki",format:"der"}).equals(buf),
        "Noncanonical Ed25519 SPKI encoding");
  return {key, id: hash(buf), der:buf};
}
function signature(signatureB64) {
  check(typeof signatureB64 === "string" && /^[a-zA-Z0-9+/]+={0,2}$/.test(signatureB64),
        "Missing signed PoP message");
  const buf = Buffer.from(signatureB64, "base64");
  check(buf.length === 64 && buf.toString("base64") === signatureB64,
        "Invalid Ed25519 signature format");
  return buf;
}
function signedMessage(tag, fields) {
  // Encode the primitive signed fields without serializing an Array object.
  // JSON.stringify(fields) invokes an inherited Array.prototype.toJSON hook,
  // which can replace ALL signed fields with attacker-controlled bytes.
  check(Array.isArray(fields), "Invalid PoP signed field list");
  let encoded = "[";
  for (let i = 0; i < fields.length; i++) {
    const field = fields[i];
    check(typeof field === "string" || typeof field === "number",
          "Invalid PoP signed field type");
    if (i) encoded += ",";
    encoded += JSON.stringify(field);
  }
  encoded += "]";
  return Buffer.from(PREFIX + "\n" + tag + "\n" + encoded, "utf8");
}
function verify(pub, tag, fields, sig) {
  return crypto.verify(null, signedMessage(tag, fields), pub, signature(sig));
}
function requireNumber(value, name, allowZero=false) {
  check(Number.isSafeInteger(value) && value >= (allowZero ? 0 : 1),
        "Invalid positive safe integer: " + name);
}
// Only explicit Privi research-chain IDs are supported. A real chain ID is
// never inferred from an RPC, a client string, or another token network.
function positionStamp(company, positionSeq) {
  check(typeof company === "string" && ORGANIZATION.test(company), "Invalid company");
  requireNumber(positionSeq, "PoP anchor sequence");
  return "PoP:" + company + ":VALIDATOR/AUTH:" +
    String(positionSeq).padStart(6, "0");
}
function admissionFields(chainId, genesisHash, epoch, operator, faultDomain,
                         company, positionSeq, validatorId, anchorBlockHash) {
  return [chainId,genesisHash,epoch,operator,faultDomain,company,
          positionSeq,validatorId,anchorBlockHash];
}
function canonicalOwnData(record, required, label) {
  // Verify and snapshot declared own data descriptors. A Proxy get trap
  // must not substitute a signed registry or validator after validation.
  const error="Noncanonical PoP " + label + " record: unsigned fields or accessors";
  check(record && typeof record === "object" && !Array.isArray(record) &&
        Object.getPrototypeOf(record) === Object.prototype &&
        Reflect.ownKeys(record).length === required.length, error);
  const snapshot=Object.create(null);
  for(const field of required) {
    const d=Object.getOwnPropertyDescriptor(record,field);
    check(d && Object.hasOwn(d,"value") && d.enumerable,error);
    snapshot[field]=d.value;
  }
  return snapshot;
}
function parseRegistry(registry, governanceKey) {
  const {chainId,genesisHash,epoch,mode,validators}=canonicalOwnData(registry,
    ["chainId","genesisHash","epoch","mode","validators"],"registry");
  check(typeof chainId === "string" && CHAIN.test(chainId), "Unexpected PoP research chain");
  check(typeof genesisHash === "string" && HEX.test(genesisHash),
        "Invalid PoP research genesis");
  requireNumber(epoch,"epoch");
  check(mode === TRUSTED_MODE,"Cannot run candidate as mainnet consensus");
  check(Array.isArray(validators),"PoP requires 4..31 attested research validators");
  // Read the actual array length and index data descriptors once. A Proxy
  // may invent a different length, index value, or Symbol.iterator via get
  // traps; none of those values may determine the admitted signer roster.
  const lengthDescriptor=Object.getOwnPropertyDescriptor(validators,"length");
  const validatorCount=lengthDescriptor && lengthDescriptor.value;
  check(Number.isSafeInteger(validatorCount) && validatorCount>=4 &&
        validatorCount<=31,"PoP requires 4..31 attested research validators");
  const admittedRecords=[];
  check(Object.getPrototypeOf(validators) === Array.prototype &&
        Reflect.ownKeys(validators).length === validatorCount + 1 &&
        Array.from({length:validatorCount},(_,i)=>{
          const d=Object.getOwnPropertyDescriptor(validators,String(i));
          if(!d || !Object.hasOwn(d,"value") || !d.enumerable)return false;
          admittedRecords.push(d.value);
          return true;
        }).every(Boolean),
        "Noncanonical PoP validator roster: dense plain data array required");
  const gov = publicKey(governanceKey);
  const ids = new Set(), operators = new Set(), domains=new Set(), positions=new Set();
  const validated=[];
  for (const v of admittedRecords) {
    const {id,keySpkiBase64,operatorId,faultDomain,companyId,positionSequence,
      anchorBlockHash,positionHash,admissionSignature}=canonicalOwnData(v,
      ["id","keySpkiBase64","operatorId","faultDomain","companyId",
       "positionSequence","anchorBlockHash","positionHash","admissionSignature"],
      "validator");
    const pub=publicKey(keySpkiBase64);
    check(id===pub.id, "Validator ID must bind actual Ed25519 public key");
    check(typeof operatorId==="string" && ORGANIZATION.test(operatorId),
          "Invalid operator");
    check(typeof faultDomain==="string" && DOMAIN.test(faultDomain),
          "Invalid fault domain");
    const stamp=positionStamp(companyId,positionSequence);
    const expectedPositionHash=hash(Buffer.from(stamp,"utf8"));
    check(positionHash===expectedPositionHash, "PoP validator anchor stamp mismatch");
    check(typeof anchorBlockHash==="string" && HEX.test(anchorBlockHash),
          "Verified native Privi position-block commitment missing");
    check(!ids.has(id) && !operators.has(operatorId) &&
          !domains.has(faultDomain) && !positions.has(stamp),
          "Duplicated validator, operator, failure domain, or PoP position");
    const fields=admissionFields(chainId,genesisHash,epoch,operatorId,faultDomain,
                companyId,positionSequence,id,anchorBlockHash);
    check(verify(gov.key,"admit",fields,admissionSignature),
          "PoP admission signature invalid or absent");
    ids.add(id);operators.add(operatorId);domains.add(faultDomain);positions.add(stamp);
    validated.push({id,pub:pub.key,operatorId,faultDomain,stamp,positionHash,
                    anchorBlockHash});
  }
  // Research proposer election hashes this order. Locale collation can vary
  // across hosts/ICU versions; fixed lowercase-hex fingerprints must use
  // raw UTF-16/ASCII code-unit ordering on every research node.
  validated.sort((a,b)=>a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  // No PRVI staking power, token holdings or IoT event count affects
  // committee weight. This is *proposed* equal-one-vote research admission.
  const quorum=Math.floor(2*validated.length/3)+1;
  // Freeze identity metadata used in quorum decisions. Map contents remain
  // externally accessible for lookup, so certificate verification rechecks
  // every map entry against these pinned validator records.
  validated.forEach(Object.freeze);
  Object.freeze(validated);
  const byId=new Map(validated.map(v=>[v.id,v]));
  // Pin the governance root that actually verified all admission signatures.
  // Adjacent epochs must not silently switch authorities with an identical validator set.
  const committee=Object.freeze({chainId,genesisHash,epoch,mode,
    governanceKeyId:gov.id,quorum,validators:validated,byId});
  validatedCommittees.add(committee);
  return committee;
}
function proposer(committee,height,round) {
  // Election results must be bound to an admitted, unmodified committee.
  // A caller-constructed roster cannot serve as a PoP proposer authority.
  assertValidatedCommittee(committee);
  requireNumber(height,"height");requireNumber(round,"round",true);
  // Bind this deterministic RESEARCH election to the governance-admitted
  // signer roster, not only epoch and committee size. This is NOT a
  // randomness beacon, anti-censorship proof, or production leader election.
  // Use direct indexed reads of the frozen, admitted signer roster.
  // Inherited Array.prototype.map overrides must not substitute a different
  // research proposer seed or cause honest nodes to elect different leaders.
  // Preserve the existing v2 seed bytes, including JSON primitive encoding.
  const prefix=JSON.stringify("Privi/PoP/Research/ProposerElection/v2")+","+
    JSON.stringify(committee.chainId)+","+
    JSON.stringify(committee.genesisHash)+","+
    JSON.stringify(committee.epoch)+","+
    JSON.stringify(committee.governanceKeyId);
  let roster="";
  for(let i=0;i<committee.validators.length;i++){
    if(i)roster+=",";
    roster+=JSON.stringify(committee.validators[i].id);
  }
  const seedBytes="["+prefix+",["+roster+"],"+
                  JSON.stringify(height)+","+JSON.stringify(round)+"]";
  const seed=hash(Buffer.from(seedBytes,"utf8"));
  const slot=Number(BigInt(seed)%BigInt(committee.validators.length));
  return committee.validators[slot].id;
}
function proposalFields(committee,height,round,previousBlockHash,blockHash,proposerId) {
  requireNumber(height,"height");requireNumber(round,"round",true);
  check(typeof previousBlockHash==="string" && HEX.test(previousBlockHash),
        "Invalid previous PoP block hash");
  check(typeof blockHash==="string" && HEX.test(blockHash) &&
        blockHash!==previousBlockHash,"Invalid current PoP block hash");
  check(nativeMapHas.call(committee.byId,proposerId) &&
        proposer(committee,height,round)===proposerId, "Invalid PoP proposer");
  return [committee.chainId,committee.genesisHash,committee.epoch,height,
          round,previousBlockHash,blockHash,proposerId];
}
// Every public verification/signing path must require the exact committee
// produced by governance-signature validation. A caller-supplied map, even
// with matching keys, must never acquire research signing authority.
function assertValidatedCommittee(committee) {
  check(committee && validatedCommittees.has(committee),
        "Unverified PoP committee: parse signed governance admission first");
  const count=committee.validators.length;
  check(count>=4 && count<=31 &&
        committee.quorum===Math.floor(2*count/3)+1 &&
        committee.byId instanceof Map && nativeMapSize.call(committee.byId)===count,
        "PoP committee quorum or membership metadata inconsistent");
  for(const validator of committee.validators) {
    check(nativeMapGet.call(committee.byId,validator.id)===validator,
          "PoP committee membership changed after admission");
  }
}
function verifyProposal(committee, proposal) {
  assertValidatedCommittee(committee);
  check(proposal && typeof proposal==="object" && !Array.isArray(proposal),
        "Proposal missing");
  // Reject accessors, inherited properties and unsigned extra metadata before
  // reading any untrusted proposal field. A signature only authenticates the
  // six canonical research fields, never a caller's added finality claims.
  const required=["height","round","previousBlockHash","blockHash","proposerId","signature"];
  check(Object.getPrototypeOf(proposal)===Object.prototype &&
        Reflect.ownKeys(proposal).length===required.length,
        "PoP proposal requires plain own canonical data fields without extras");
  // Capture the same descriptor values that passed structural validation.
  // A Proxy get trap must not swap a different signed proposal into quorum
  // verification while its declared own data fields describe another block.
  const canonical={};
  for(const field of required){
    const descriptor=Object.getOwnPropertyDescriptor(proposal,field);
    check(descriptor && Object.hasOwn(descriptor,"value") &&
          descriptor.enumerable,
          "PoP proposal requires plain own canonical data fields without extras");
    canonical[field]=descriptor.value;
  }
  const {height,round,previousBlockHash,blockHash,proposerId,
    signature:proposalSig}=canonical;
  const fields=proposalFields(committee,height,round,
                              previousBlockHash,blockHash,proposerId);
  check(verify(nativeMapGet.call(committee.byId,proposerId).pub,"propose",fields,proposalSig),
        "Unsigned/forged PoP proposal");
  return fields;
}
function voteFields(proposalFields, validatorId) {
  // A hostile inherited Array.prototype[Symbol.iterator] could substitute
  // a different signed block hash when spreading the verified proposal.
  // Copy the eight internally validated fields by index instead.
  check(Array.isArray(proposalFields) && proposalFields.length===8,
        "Invalid PoP proposal vote fields");
  const fields=new Array(9);
  for(let i=0;i<8;i++)fields[i]=proposalFields[i];
  fields[8]=validatorId;
  return fields;
}
function verifyCertificate(committee, proposal, votes) {
  // verifyProposal enforces attested committee identity and frozen membership
  // before the caller can use a proposal in either a certificate or signature.
  const fields=verifyProposal(committee,proposal);
  // The vote container itself is unsigned input. Reject sparse arrays,
  // index getters and attached metadata (including hidden/symbol keys)
  // before iterating votes. A decorated array must not imply finality.
  check(Array.isArray(votes) &&
        Object.getPrototypeOf(votes) === Array.prototype,
        "Malformed PoP vote certificate");
  // Snapshot own data descriptors rather than trusting Proxy get traps or
  // Symbol.iterator. Otherwise an apparently empty vote array can yield an
  // entirely different, signed quorum from a hostile iterator.
  const lengthDescriptor=Object.getOwnPropertyDescriptor(votes,"length");
  const count=lengthDescriptor && lengthDescriptor.value;
  check(Number.isSafeInteger(count) && count>=0 &&
        count<=committee.validators.length,
        "Malformed PoP vote certificate");
  check(Reflect.ownKeys(votes).length===count+1,
        "PoP votes require a dense plain array without unsigned metadata or accessors");
  const canonicalVotes=[];
  for(let i=0;i<count;i++){
    const descriptor=Object.getOwnPropertyDescriptor(votes,String(i));
    check(descriptor && Object.hasOwn(descriptor,"value") &&
          descriptor.enumerable,
          "PoP votes require a dense plain array without unsigned metadata or accessors");
    canonicalVotes.push(descriptor.value);
  }
  const seen=new Set();
  // Iterate the descriptor-snapshotted vote array by index. A poisoned
  // Array.prototype[Symbol.iterator] must not substitute a different quorum.
  for(let voteIndex=0;voteIndex<canonicalVotes.length;voteIndex++) {
    const vote=canonicalVotes[voteIndex];
    check(vote && typeof vote==="object","Invalid PoP vote");
    // Signed commit fields do not authenticate arbitrary caller metadata.
    // Reject accessors, inherited values and extra finality claims before
    // reading signer identity or signature. The local research signer adds
    // only the explicitly non-production researchOnly:true marker.
    const keys=Reflect.ownKeys(vote);
    const marker=Object.getOwnPropertyDescriptor(vote,"researchOnly");
    // Snapshot the exact own data descriptors used for validation. A Proxy
    // getter may supply a signed quorum different from its declared votes.
    // Never invoke inherited Array.prototype.map/ every to select the two
    // authenticated vote fields: a polluted map could substitute descriptors
    // from another, legitimately signed voter for an unadmitted declared vote.
    const idDescriptor=Object.getOwnPropertyDescriptor(vote,"validatorId");
    const sigDescriptor=Object.getOwnPropertyDescriptor(vote,"signature");
    const ownData=d=>d && Object.hasOwn(d,"value") && d.enumerable;
    check(Object.getPrototypeOf(vote)===Object.prototype &&
          // A Proxy can omit a configurable researchOnly key from ownKeys.
          // The two-field form must not secretly declare that marker.
          ((keys.length===2 && marker===undefined) ||
           (keys.length===3 && marker &&
            Object.hasOwn(marker,"value") && marker.value===true &&
            marker.enumerable)) &&
          ownData(idDescriptor) && ownData(sigDescriptor),
          "PoP vote requires plain own canonical data fields without extras");
    const validatorId=idDescriptor.value,voteSignature=sigDescriptor.value;
    const signer=nativeMapGet.call(committee.byId,validatorId);
    check(!!signer,"Unadmitted PoP voter");
    check(!seen.has(validatorId),"Duplicate PoP voter");
    check(verify(signer.pub,"commit",voteFields(fields,validatorId),voteSignature),
          "Forged or wrong-epoch/chain/round PoP vote");
    seen.add(validatorId);
  }
  check(seen.size>=committee.quorum,
        "Insufficient independently signed PoP quorum");
  return Object.freeze({
    valid:true,
    protocol:"Point of Position candidate (not live consensus)",
    chainId:committee.chainId,genesisHash:committee.genesisHash,
    governanceKeyId:committee.governanceKeyId,epoch:committee.epoch,
    // Bind reported certificate metadata to the same snapshot verified by
    // the proposer signature. Untrusted Proxy getters can change on reread.
    height:fields[3],round:fields[4],
    previousBlockHash:fields[5],
    blockHash:fields[6],signers:seen.size,quorum:committee.quorum,
    // Attribute the verified research votes to exact admitted signer identities.
    // Sort independently of input vote order and freeze the nested array:
    // freezing the outer certificate alone would not protect its members.
    signerIds:Object.freeze([...seen].sort()),
    // A quorum of valid research signatures is NOT a finalized chain block.
    // Consumers must not mistake this signed-proposal check for execution,
    // independent validator control, or production financial finality.
    finalized:false,validatesExecution:false,
    validatorIndependenceVerified:false,productionConsensus:false
  });
}
// This lock is ephemeral test logic and is not crash-safe. It MUST NOT be
// plugged directly into a live validator. One instance represents a single
// chain/genesis; no automatic recovery, network transport, or view change.
// Match the durable research guard's conservative rule: epoch transitions
// cannot clear a same-height commitment, even when the block hash is equal.
class ResearchVoteLock {
  // Never expose a writable Map that callers could clear to bypass a height
  // commitment. This is only same-process research hardening, not durable
  // signing-state recovery or a defense against a compromised JS runtime.
  #commits = new Map();
  constructor(){Object.freeze(this);}
  accept(epoch,height,round,validatorId,blockHash,previousBlockHash) {
    requireNumber(epoch,"epoch");requireNumber(height,"height");requireNumber(round,"round",true);
    check(typeof validatorId==="string" && HEX.test(validatorId),
          "Invalid voter");
    check(typeof blockHash==="string" && HEX.test(blockHash),
          "Invalid vote block hash");
    check(typeof previousBlockHash==="string" && HEX.test(previousBlockHash) &&
          previousBlockHash!==blockHash,"Invalid vote previous block hash");
    // Epoch is deliberately excluded. An unreviewed validator-set transition
    // must not reset a previous same-height signing commitment. Parent hash
    // must also match: identical child hashes with different claimed ancestry
    // are conflicting signed statements, even when rounds differ.
    // A poisoned Array.prototype.toJSON can make serialized lock keys change
    // between calls and permit conflicting same-height votes. The validated
    // safe-integer height and fixed-width hex signer ID are unambiguous here.
    const key=height+":"+validatorId;
    const old=nativeMapGet.call(this.#commits,key);
    check(!old || old.epoch===epoch,"PoP unreviewed same-height epoch transition rejected");
    check(!old || old.blockHash===blockHash,"PoP conflicting-height double-sign rejected");
    check(!old || old.previousBlockHash===previousBlockHash,
          "PoP conflicting-height parent-link double-sign rejected");
    nativeMapSet.call(this.#commits,key,{epoch,blockHash,previousBlockHash});
  }
}
module.exports={
  hash,publicKey,signedMessage,parseRegistry,positionStamp,proposer,
  proposalFields,verifyProposal,voteFields,verifyCertificate,ResearchVoteLock,TRUSTED_MODE,
  assertValidatedCommittee
};
