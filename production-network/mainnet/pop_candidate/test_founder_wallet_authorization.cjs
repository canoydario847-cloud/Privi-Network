"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const {
  hash,signedMessage,positionStamp,parseRegistry,TRUSTED_MODE,
  OWNER_EVM_WALLET,OWNER_COMPANY_ID,OWNER_OPERATOR_ID
} = require("./engine.cjs");
const {
  DOMAIN,buildChallenge,verifyEip191Signer,verifyFounderResearchAuthorization
} = require("./founder_wallet_authorization.cjs");

// This test never uses, generates or stores the real founder's private key.
// Ephemeral wallet signers prove that the generic EIP-191 verifier works;
// the STRICT founder gate must reject all of those signatures.
const modulePath = process.env.PRIVI_POP_ETHERS_PATH;
if (!modulePath || !modulePath.includes("privi-pop-ethers"))
  throw Error("Isolated pinned ethers verifier is required for research tests");
const ethers = require(modulePath);

function makeEd25519() {
  const keys=crypto.generateKeyPairSync("ed25519");
  const der=keys.publicKey.export({type:"spki",format:"der"});
  return {id:hash(der),pub:der.toString("base64"),key:keys.privateKey};
}
function fixture() {
  const gov=makeEd25519(),keys=Array.from({length:4},makeEd25519);
  const chainId="privi-pop-research-owner-bind",genesisHash="0x"+"a".repeat(64),epoch=7;
  const registry={
    chainId,genesisHash,epoch,mode:TRUSTED_MODE,
    operatorId:OWNER_OPERATOR_ID,ownerWallet:OWNER_EVM_WALLET,
    validators:keys.map((k,i)=>{
      const companyId=OWNER_COMPANY_ID,operatorId=OWNER_OPERATOR_ID;
      const positionSequence=i+1,faultDomain="node"+i+".owner.example";
      const anchorBlockHash=hash(Buffer.from("researched-anchor-"+i));
      const fields=[chainId,genesisHash,epoch,OWNER_EVM_WALLET,operatorId,
        faultDomain,companyId,positionSequence,k.id,anchorBlockHash];
      return {
        id:k.id,keySpkiBase64:k.pub,operatorId,faultDomain,companyId,positionSequence,
        positionHash:hash(Buffer.from(positionStamp(companyId,positionSequence))),
        anchorBlockHash,admissionSignature:crypto.sign(
          null,signedMessage("admit",fields),gov.key).toString("base64")
      };
    })
  };
  parseRegistry(registry,gov.pub);
  return {registry,govKey:gov.pub};
}
function approval(expiresAtSeconds=1800003000) {
  return {expiresAtSeconds,nonce:"0x"+"3".repeat(64)};
}

test("challenge binds Ed25519 root, four PoP validators, founder address, chain, epoch, genesis, expiry and nonce",()=>{
  const f=fixture(),a=approval(),challenge=buildChallenge(f.registry,f.govKey,a);
  assert.equal(challenge.committee.validators.length,4);
  assert.ok(challenge.message.startsWith(DOMAIN+"\n"));
  assert.ok(challenge.message.includes("ownerWallet="+OWNER_EVM_WALLET));
  assert.ok(challenge.message.includes("RESEARCH ONLY"));
  assert.ok(challenge.message.includes("epoch=7"));
  assert.ok(challenge.message.includes("nonce="+a.nonce));
  assert.ok(challenge.message.includes("committeeSHA256="+challenge.committeeHash));
  assert.match(challenge.committeeHash,/^0x[0-9a-f]{64}$/);
});

test("ephemeral EVM wallet personal_sign has cryptographically verified caller identity",async()=>{
  const f=fixture(),a=approval(),wallet=ethers.Wallet.createRandom();
  const challenge=buildChallenge(f.registry,f.govKey,a);
  const sig=await wallet.signMessage(challenge.message);
  assert.equal(verifyEip191Signer(challenge.message,sig,wallet.address,ethers),wallet.address);
  assert.throws(()=>verifyEip191Signer(challenge.message,sig,OWNER_EVM_WALLET,ethers),
    /not from the required Privi wallet/);
  assert.throws(()=>verifyEip191Signer(challenge.message,sig,"0x"+"f".repeat(40),ethers),
    /not from the required Privi wallet/);
  assert.throws(()=>verifyEip191Signer(challenge.message,"0x123",wallet.address,ethers),
    /Malformed EIP-191/);
  assert.throws(()=>verifyEip191Signer("Unscoped message",sig,wallet.address,ethers),
    /domain required/);
});

test("real founder gate refuses an unrelated wallet, even if it signed entire correct proposal",async()=>{
  const f=fixture(),a=approval(),wallet=ethers.Wallet.createRandom();
  a.signature=await wallet.signMessage(buildChallenge(f.registry,f.govKey,a).message);
  assert.throws(()=>verifyFounderResearchAuthorization({
    registry:f.registry,governancePublicKeySpkiBase64:f.govKey,
    approval:a,ethers,nowSeconds:1800000000
  }),/not from the required Privi wallet/);
});

test("cannot authorize without founder signature or with expired, indefinite or malformed approval",()=>{
  const f=fixture(),a=approval();
  const base={registry:f.registry,governancePublicKeySpkiBase64:f.govKey,
    ethers,nowSeconds:1800000000};
  assert.throws(()=>verifyFounderResearchAuthorization({...base,approval:a}),
    /Malformed EIP-191/);
  assert.throws(()=>verifyFounderResearchAuthorization({
    ...base,approval:{...a,expiresAtSeconds:1799999999,signature:"0x"+"1".repeat(130)}
  }),/expired/);
  assert.throws(()=>verifyFounderResearchAuthorization({
    ...base,approval:{...a,expiresAtSeconds:1800700000,signature:"0x"+"1".repeat(130)}
  }),/7-day validity/);
  assert.throws(()=>buildChallenge(f.registry,f.govKey,{...a,nonce:"0x"+"0".repeat(64)}),
    /unique nonzero/);
});

test("replay across other epoch, genesis, validator set and governance root must change signed challenge",()=>{
  const f=fixture(),a=approval(),other=fixture();
  const original=buildChallenge(f.registry,f.govKey,a).message;
  assert.notEqual(buildChallenge(other.registry,other.govKey,a).message,original);
  const changedEpoch=structuredClone(f.registry);
  changedEpoch.epoch++;
  // Validator admissions bind epoch, so a registry mutation fails closed
  // even before the owner's signature is checked.
  assert.throws(()=>buildChallenge(changedEpoch,f.govKey,a),/admission signature/);
  const changedGenesis=structuredClone(f.registry);
  changedGenesis.genesisHash="0x"+"b".repeat(64);
  assert.throws(()=>buildChallenge(changedGenesis,f.govKey,a),/admission signature/);
  const removed=structuredClone(f.registry);
  removed.validators.pop();
  assert.throws(()=>buildChallenge(removed,f.govKey,a),/4..31/);
  const duplicated=structuredClone(f.registry);
  duplicated.validators[1]=duplicated.validators[0];
  assert.throws(()=>buildChallenge(duplicated,f.govKey,a),/Duplicated/);
  const nonceChanged=buildChallenge(f.registry,f.govKey,{...a,nonce:"0x"+"4".repeat(64)});
  assert.notEqual(nonceChanged.message,original);
  const expiresChanged=buildChallenge(f.registry,f.govKey,{...a,expiresAtSeconds:a.expiresAtSeconds+1});
  assert.notEqual(expiresChanged.message,original);
});

test("EIP-191 signature for another challenge is rejected by the strict founder verifier",async()=>{
  const f=fixture(),a=approval(),testWallet=ethers.Wallet.createRandom();
  const signed=buildChallenge(f.registry,f.govKey,a).message;
  const sig=await testWallet.signMessage(signed);
  const different=buildChallenge(f.registry,f.govKey,
    {...a,nonce:"0x"+"5".repeat(64)}).message;
  assert.throws(()=>verifyEip191Signer(different,sig,testWallet.address,ethers),
    /not from the required Privi wallet/);
});

test("research committee cannot be confused with a production blockchain",()=>{
  const f=fixture(),a=approval(),pretend=structuredClone(f.registry);
  pretend.mode="production-mainnet";
  assert.throws(()=>buildChallenge(pretend,f.govKey,a),/Cannot run candidate as mainnet/);
});
