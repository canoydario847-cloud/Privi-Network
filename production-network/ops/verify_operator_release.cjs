"use strict";
/*
 * Offline Privi operator release ceremony EVIDENCE verification.
 * Read only. Never signs real genesis, issues PRVI, transmits keys, runs a
 * validator, starts consensus, or grants mainnet launch authority.
 *
 * A distinct trust roster must be approved out of band. Four signatures
 * prove possession of four private keys; NOT four independent operators.
 */
const fs = require("node:fs");
const crypto = require("node:crypto");
const BASE = "Privi/OperatorReleaseEvidence/v1";
const FORMAT = "PriviMainnetReleaseEvidence/v1";
const ROSTER_FORMAT = "PriviIndependentOperatorRoster/v1";
const HEX64 = /^[0-9a-f]{64}$/;
const HEX40 = /^[0-9a-f]{40}$/;
const ID = /^[A-Z][A-Z0-9_-]{2,39}$/;
const DOMAIN = /^[a-z0-9][a-z0-9._-]{2,100}$/;
const DENIED_EVM_IDS = new Set([0,1,56,97,1337,31337,4221,262144]);

function need(condition, reason) { if (!condition) throw Error(reason); }
function object(x, keys, description) {
  need(x !== null && typeof x === "object" && !Array.isArray(x),
       description + " must be an object");
  const actual = Object.keys(x).sort();
  need(JSON.stringify(actual) === JSON.stringify([...keys].sort()),
       description + " has missing or unknown keys");
}
function fileHash(filename) {
  need(typeof filename === "string" && filename.length > 0, "Missing file path");
  const stat = fs.lstatSync(filename);
  need(stat.isFile() && !stat.isSymbolicLink(), "Source must be a regular non-symlink file");
  const fd = fs.openSync(filename, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const h = crypto.createHash("sha256");
    const buf = Buffer.allocUnsafe(1024*1024);
    let n;
    while ((n = fs.readSync(fd,buf,0,buf.length,null)) > 0) h.update(buf.subarray(0,n));
    return h.digest("hex");
  } finally { fs.closeSync(fd); }
}
function pubkey(encoded) {
  need(typeof encoded==="string" && /^[A-Za-z0-9+/]+={0,2}$/.test(encoded),
       "Missing canonical operator Ed25519 public key");
  const bytes = Buffer.from(encoded,"base64");
  need(bytes.length>=32 && bytes.length<=128 && bytes.toString("base64")===encoded,
       "Noncanonical operator Ed25519 public key");
  const key = crypto.createPublicKey({key:bytes,format:"der",type:"spki"});
  need(key.asymmetricKeyType==="ed25519", "Operator signing key must be Ed25519");
  return key;
}
function signature(encoded) {
  need(typeof encoded==="string" && /^[A-Za-z0-9+/]+={0,2}$/.test(encoded),
       "Missing canonical release signature");
  const bytes=Buffer.from(encoded,"base64");
  need(bytes.length===64 && bytes.toString("base64")===encoded,
       "Operator signature must be canonical Ed25519");
  return bytes;
}
function validateRoster(roster) {
  object(roster,["format","operators"],"trust roster");
  need(roster.format===ROSTER_FORMAT, "Unexpected trust roster format");
  need(Array.isArray(roster.operators) && roster.operators.length>=4 &&
       roster.operators.length<=31, "Four to 31 separately vetted operators required");
  const operators=new Map(), domains=new Set(), keys=new Set();
  for(const op of roster.operators) {
    object(op,["operator_id","fault_domain","public_key_spki_base64"],"roster operator");
    need(typeof op.operator_id==="string" && ID.test(op.operator_id),
         "Operator ID missing or malformed");
    need(typeof op.fault_domain==="string" && DOMAIN.test(op.fault_domain),
         "Fault-domain ID missing or malformed");
    pubkey(op.public_key_spki_base64);
    need(!operators.has(op.operator_id), "Duplicate operator identifier");
    need(!domains.has(op.fault_domain), "Duplicate claimed fault domain");
    need(!keys.has(op.public_key_spki_base64), "Duplicate operator public key");
    operators.set(op.operator_id,op);
    domains.add(op.fault_domain);
    keys.add(op.public_key_spki_base64);
  }
  return operators;
}
function canonicalPayload(release) {
  object(release,[
    "cosmos_chain_id","evm_chain_id","base_denom","max_supply_whole_prvi",
    "consensus_protocol","genesis_sha256","binary_sha256",
    "source_commit","planned_genesis_utc"
  ],"release commitment");
  need(typeof release.cosmos_chain_id==="string" &&
       /^privi-[a-z0-9-]{3,60}$/.test(release.cosmos_chain_id) &&
       !/^privi-(?:dev|test|local|staging)(?:-|$)/.test(release.cosmos_chain_id),
       "Non-developer Privi Cosmos chain identity required");
  need(Number.isSafeInteger(release.evm_chain_id) &&
       release.evm_chain_id>0 &&
       !DENIED_EVM_IDS.has(release.evm_chain_id),
       "Unapproved public/developer EVM chain identity");
  need(release.base_denom==="aprvi", "Native denomination must be aprvi");
  need(release.max_supply_whole_prvi==="1000000000",
       "Immutable maximum supply must be 1 billion PRVI");
  need(release.consensus_protocol==="Point of Position",
       "Native Point of Position required (not PoS/PoSA)");
  need(typeof release.genesis_sha256==="string" &&
       HEX64.test(release.genesis_sha256), "Malformed genesis digest");
  need(typeof release.binary_sha256==="string" &&
       HEX64.test(release.binary_sha256), "Malformed node-binary digest");
  need(typeof release.source_commit==="string" && HEX40.test(release.source_commit),
       "Exact 40-character source commit required");
  need(typeof release.planned_genesis_utc==="string" &&
       /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(release.planned_genesis_utc) &&
       !Number.isNaN(Date.parse(release.planned_genesis_utc)) &&
       new Date(release.planned_genesis_utc).toISOString().replace(".000Z","Z") ===
       release.planned_genesis_utc, "Canonical UTC genesis timestamp required");
  // Use a positional, versioned and domain-separated transcript.
  return [
    FORMAT,release.cosmos_chain_id,release.evm_chain_id,release.base_denom,
    release.max_supply_whole_prvi,release.consensus_protocol,
    release.genesis_sha256,release.binary_sha256,
    release.source_commit,release.planned_genesis_utc
  ];
}
function message(release,op) {
  const parts=canonicalPayload(release);
  object(op,["operator_id","fault_domain","public_key_spki_base64"],"operator transcript");
  // Bind each vote to its exact signer identity, not just release fields.
  return Buffer.from(BASE+"\n"+JSON.stringify([...parts,
    op.operator_id,op.fault_domain,op.public_key_spki_base64]),"utf8");
}
function verifyCeremony({manifest,trustRoster,genesisPath,binaryPath}) {
  object(manifest,["format","release","signatures"],"release manifest");
  need(manifest.format===FORMAT, "Unsupported release manifest");
  const members=validateRoster(trustRoster);
  const release=manifest.release;
  canonicalPayload(release);
  need(fileHash(genesisPath)===release.genesis_sha256,
       "Genesis bytes do not match the signed SHA-256");
  need(fileHash(binaryPath)===release.binary_sha256,
       "Node binary bytes do not match the signed SHA-256");
  // A literal chain_id in the genesis is an additional cross-check, not a
  // substitute for native-genesis protocol/denomination/security auditing.
  const genesisBytes=fs.readFileSync(genesisPath);
  need(genesisBytes.length <= 32*1024*1024, "Genesis JSON too large for offline review");
  const parsed=JSON.parse(genesisBytes.toString("utf8"));
  need(parsed && typeof parsed==="object" &&
       parsed.chain_id===release.cosmos_chain_id,
       "Signed genesis and Cosmos chain IDs disagree");
  need(Array.isArray(manifest.signatures) &&
       manifest.signatures.length===members.size,
       "Exactly one signature from each approved operator required");
  const seen=new Set();
  for (const entry of manifest.signatures) {
    object(entry,["operator_id","signature_base64"],"operator signature");
    const op=members.get(entry.operator_id);
    need(op && !seen.has(entry.operator_id), "Unapproved or duplicate release signer");
    need(crypto.verify(null,message(release,op),
       pubkey(op.public_key_spki_base64),signature(entry.signature_base64)),
       "Invalid or replayed operator release signature: "+entry.operator_id);
    seen.add(entry.operator_id);
  }
  need(seen.size>=4, "Insufficient signed operator evidence");
  return Object.freeze({
    verified_operator_signatures:seen.size,
    genesis_sha256:release.genesis_sha256,
    binary_sha256:release.binary_sha256,
    source_commit:release.source_commit,
    cosmos_chain_id:release.cosmos_chain_id,
    evm_chain_id:release.evm_chain_id,
    production_release_authorized:false,
    financial_mainnet_activated:false,
    limitations:"Four keys are not proof of independent operators or native PoP BFT; external custody, auditor and founder signoffs remain required."
  });
}
function main(argv) {
  need(argv.length===8 &&
       argv[0]==="--manifest" && argv[2]==="--trust-roster" &&
       argv[4]==="--genesis" && argv[6]==="--binary",
       "Usage: node verify_operator_release.cjs --manifest FILE --trust-roster FILE --genesis FILE --binary FILE");
  const [manifest,roster]=[argv[1],argv[3]].map(p=>JSON.parse(fs.readFileSync(p,"utf8")));
  const result=verifyCeremony({manifest,trustRoster:roster,
                             genesisPath:argv[5],binaryPath:argv[7]});
  process.stdout.write(JSON.stringify(result,null,2)+"\n");
}
if(require.main===module){
  try {main(process.argv.slice(2));}
  catch(e) {process.stderr.write("RELEASE EVIDENCE REJECTED: "+e.message+"\n");process.exitCode=1;}
}
module.exports={message,verifyCeremony,fileHash,validateRoster,canonicalPayload,FORMAT,ROSTER_FORMAT};
