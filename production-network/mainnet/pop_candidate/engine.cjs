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
// One legal network operator controlling four or more separate signer/host
// identities, as expressly required for Privi World Corp. These are NOT
// independent operators and must never be presented as decentralization.
const OWNER_OPERATOR_ID = "PRIVI_WORLD_CORP";
const OWNER_COMPANY_ID = "PRIVI_WORLD_CORP";
const OWNER_EVM_WALLET = "0x1990589FD200E043b8C6FD9ec5956c61b3071048";
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
  // Array order is explicit and fixed: no JS object serialization ambiguity.
  return Buffer.from(PREFIX + "\n" + tag + "\n" + JSON.stringify(fields), "utf8");
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
function admissionFields(chainId, genesisHash, epoch, ownerWallet, operator, faultDomain,
                         company, positionSeq, validatorId, anchorBlockHash) {
  return [chainId,genesisHash,epoch,ownerWallet,operator,faultDomain,company,
          positionSeq,validatorId,anchorBlockHash];
}
function parseRegistry(registry, governanceKey) {
  check(registry && typeof registry === "object" && !Array.isArray(registry),
        "PoP registry missing");
  const {chainId,genesisHash,epoch,mode,ownerWallet,operatorId,validators}=registry;
  check(typeof chainId === "string" && CHAIN.test(chainId), "Unexpected PoP research chain");
  check(typeof genesisHash === "string" && HEX.test(genesisHash),
        "Invalid PoP research genesis");
  requireNumber(epoch,"epoch");
  check(mode === TRUSTED_MODE,"Cannot run candidate as mainnet consensus");
  check(ownerWallet===OWNER_EVM_WALLET,
        "PoP research owner wallet must match sole proposed Privi founder wallet");
  check(operatorId===OWNER_OPERATOR_ID,
        "PoP research must disclose Privi World Corp as the ONE operator");
  check(Array.isArray(validators) && validators.length >= 4 &&
        validators.length <= 31,"PoP requires 4..31 attested research validators");
  const gov = publicKey(governanceKey);
  const ids = new Set(), domains=new Set(), positions=new Set();
  const validated=[];
  for (const v of validators) {
    check(v && typeof v==="object" && !Array.isArray(v), "Invalid validator");
    const {id,keySpkiBase64,operatorId,faultDomain,companyId,positionSequence,
      anchorBlockHash,positionHash,admissionSignature}=v;
    const pub=publicKey(keySpkiBase64);
    check(id===pub.id, "Validator ID must bind actual Ed25519 public key");
    check(operatorId===OWNER_OPERATOR_ID,
          "Only the disclosed Privi World Corp operator may admit research validators");
    check(companyId===OWNER_COMPANY_ID,
          "Validator PoP research positions must be Privi World Corp positions");
    check(typeof faultDomain==="string" && DOMAIN.test(faultDomain),
          "Invalid fault domain");
    const stamp=positionStamp(companyId,positionSequence);
    const expectedPositionHash=hash(Buffer.from(stamp,"utf8"));
    check(positionHash===expectedPositionHash, "PoP validator anchor stamp mismatch");
    check(typeof anchorBlockHash==="string" && HEX.test(anchorBlockHash),
          "Verified native Privi position-block commitment missing");
    check(!ids.has(id) && !domains.has(faultDomain) && !positions.has(stamp),
          "Duplicated validator, failure domain, or PoP position");
    const fields=admissionFields(chainId,genesisHash,epoch,ownerWallet,
                operatorId,faultDomain,companyId,positionSequence,id,anchorBlockHash);
    check(verify(gov.key,"admit",fields,admissionSignature),
          "PoP admission signature invalid or absent");
    ids.add(id);domains.add(faultDomain);positions.add(stamp);
    validated.push({id,pub:pub.key,operatorId,faultDomain,stamp,positionHash,
                    anchorBlockHash});
  }
  validated.sort((a,b)=>a.id.localeCompare(b.id));
  // No PRVI staking power, token holdings or IoT event count affects
  // committee weight. This is *proposed* equal-one-vote research admission.
  const quorum=Math.floor(2*validated.length/3)+1;
  const byId=new Map(validated.map(v=>[v.id,v]));
  return {chainId,genesisHash,epoch,mode,ownerWallet,operatorId,quorum,validators:validated,byId};
}
function proposer(committee,height,round) {
  requireNumber(height,"height");requireNumber(round,"round",true);
  const seed=hash(Buffer.from(JSON.stringify([
    committee.chainId,committee.genesisHash,committee.epoch,height,round
  ]),"utf8"));
  const slot=Number(BigInt(seed)%BigInt(committee.validators.length));
  return committee.validators[slot].id;
}
function proposalFields(committee,height,round,previousBlockHash,blockHash,proposerId) {
  requireNumber(height,"height");requireNumber(round,"round",true);
  check(typeof previousBlockHash==="string" && HEX.test(previousBlockHash),
        "Invalid previous PoP block hash");
  check(typeof blockHash==="string" && HEX.test(blockHash) &&
        blockHash!==previousBlockHash,"Invalid current PoP block hash");
  check(committee.byId.has(proposerId) &&
        proposer(committee,height,round)===proposerId, "Invalid PoP proposer");
  return [committee.chainId,committee.genesisHash,committee.epoch,height,
          round,previousBlockHash,blockHash,proposerId];
}
function verifyProposal(committee, proposal) {
  check(proposal && typeof proposal==="object" && !Array.isArray(proposal),
        "Proposal missing");
  const {height,round,previousBlockHash,blockHash,proposerId,signature:proposalSig}=proposal;
  const fields=proposalFields(committee,height,round,
                              previousBlockHash,blockHash,proposerId);
  check(verify(committee.byId.get(proposerId).pub,"propose",fields,proposalSig),
        "Unsigned/forged PoP proposal");
  return fields;
}
function voteFields(proposalFields, validatorId) {
  return [...proposalFields,validatorId];
}
function verifyCertificate(committee, proposal, votes) {
  const fields=verifyProposal(committee,proposal);
  check(Array.isArray(votes) && votes.length <= committee.validators.length,
        "Malformed PoP vote certificate");
  const seen=new Set();
  for(const vote of votes) {
    check(vote && typeof vote==="object","Invalid PoP vote");
    const signer=committee.byId.get(vote.validatorId);
    check(!!signer,"Unadmitted PoP voter");
    check(!seen.has(vote.validatorId),"Duplicate PoP voter");
    check(verify(signer.pub,"commit",voteFields(fields,vote.validatorId),vote.signature),
          "Forged or wrong-epoch/chain/round PoP vote");
    seen.add(vote.validatorId);
  }
  check(seen.size>=committee.quorum,
        "Insufficient independently signed PoP quorum");
  return Object.freeze({
    valid:true,
    protocol:"Point of Position candidate (not live consensus)",
    chainId:committee.chainId,epoch:committee.epoch,
    height:proposal.height,round:proposal.round,
    blockHash:proposal.blockHash,signers:seen.size,quorum:committee.quorum,
    productionConsensus:false
  });
}
// This lock is ephemeral test logic and is not crash-safe. It MUST NOT be
// plugged directly into a live validator. Signed-persistent lock + replay
// across epochs/upgrades and multi-round locking need a real protocol.
class ResearchVoteLock {
  constructor(){this.commits=new Map();}
  accept(epoch,height,round,validatorId,blockHash) {
    requireNumber(epoch,"epoch");requireNumber(height,"height");requireNumber(round,"round",true);
    check(typeof validatorId==="string" && HEX.test(validatorId),
          "Invalid voter");
    check(typeof blockHash==="string" && HEX.test(blockHash),
          "Invalid vote block hash");
    const key=JSON.stringify([epoch,height,validatorId]);
    const old=this.commits.get(key);
    check(!old || old===blockHash,"PoP conflicting-height double-sign rejected");
    this.commits.set(key,blockHash);
  }
}
module.exports={
  hash,publicKey,signedMessage,parseRegistry,positionStamp,proposer,
  proposalFields,verifyProposal,voteFields,verifyCertificate,ResearchVoteLock,TRUSTED_MODE,
  OWNER_OPERATOR_ID,OWNER_COMPANY_ID,OWNER_EVM_WALLET
};
