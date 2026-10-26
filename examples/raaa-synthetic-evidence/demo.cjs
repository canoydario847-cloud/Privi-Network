"use strict";
/*
 * Synthetic RAAA / Privi feasibility specimen; NOT a production receipt.
 *
 * No network, wallet, real approval, paid API, PHI, production Privi keys, or
 * financial mainnet access. Generates fresh TEST-ONLY Ed25519 keys in memory;
 * only public keys and two signed fictional event records are written.
 */
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const SCHEMA = "PriviRAAASyntheticEvidence/v1";
const DOMAIN = "Privi/RAAA/SyntheticEvidence/2026/v1\n";
const ZERO = "0".repeat(64);
const ROLES = ["authorization_service", "execution_reporter"];
const SHARED = [
  "tenant_id", "actor_id", "action_id", "policy_id", "policy_version",
  "policy_sha256", "approval_id", "approval_evidence_type"
];
function check(ok, message) { if (!ok) throw new Error(message); }
function canonical(value) {
  if (value === null || typeof value === "string" ||
      typeof value === "boolean" || typeof value === "number") {
    check(typeof value !== "number" || Number.isFinite(value), "Non-finite JSON number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  check(value && typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype,
        "Expected plain JSON object");
  return "{" + Object.keys(value).sort().map(k =>
    JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
}
function sha(bytes) { return crypto.createHash("sha256").update(bytes).digest("hex"); }
function fieldsOf(event) {
  const {entry_hash, signature_b64, ...fields} = event;
  return fields;
}
function hashEvent(event) {
  return sha(Buffer.from(DOMAIN + canonical(fieldsOf(event)), "utf8"));
}
function keyId(publicDer) { return "sha256:" + sha(publicDer); }
function freshSigner() {
  const pair = crypto.generateKeyPairSync("ed25519");
  const der = pair.publicKey.export({format:"der",type:"spki"});
  return {privateKey:pair.privateKey,
          publicRecord:{public_key_spki_base64:der.toString("base64"),key_id:keyId(der)}};
}
function signEvent(event, privateKey) {
  const entry_hash = hashEvent(event);
  const signature_b64 = crypto.sign(null,Buffer.from(entry_hash,"hex"),privateKey).toString("base64");
  return {...event,entry_hash,signature_b64};
}
function makeDemo() {
  const authorization = freshSigner();
  const execution = freshSigner();
  const common = {
    tenant_id:"tenant-SYNTHETIC-001", actor_id:"agent-SYNTHETIC-001",
    action_id:"action-SYNTHETIC-001", policy_id:"policy-SYNTHETIC",
    policy_version:"v7",policy_sha256:sha(Buffer.from(
      "Synthetic policy v7: allow synthetic categorization only","utf8")),
    approval_id:"approval-SYNTHETIC-001",
    approval_evidence_type:"reference-only-not-human-verified"
  };
  const decision = signEvent({
    sequence:1, event_id:"event-SYNTHETIC-decision-001",
    kind:"authorization_decision",signer_role:"authorization_service",
    occurred_at:"2026-10-25T16:00:00.000Z",
    ...common,software_version:"policy-stub/0.1.0",
    result:"allow",previous_entry_hash:ZERO
  },authorization.privateKey);
  const outcome = signEvent({
    sequence:2,event_id:"event-SYNTHETIC-execution-001",
    kind:"execution_report",signer_role:"execution_reporter",
    occurred_at:"2026-10-25T16:00:01.000Z",
    ...common,software_version:"executor-stub/0.1.0",
    result:"reported_success",
    external_ack_id:"ACK-SYNTHETIC-not-an-external-system",
    authorization_entry_hash:decision.entry_hash,
    previous_entry_hash:decision.entry_hash
  },execution.privateKey);
  return {
    receipt:{
      schema:SCHEMA,synthetic_only:true,
      trust_statement:"Signed records of fictional assertions; NOT proof that an actual authorized action occurred.",
      events:[decision,outcome],head_hash:outcome.entry_hash
    },
    trust:{
      schema:SCHEMA,synthetic_only:true,
      issuer:"locally-generated-ephemeral-test-keys-not-Privi-production",
      trusted_signers:{
        authorization_service:authorization.publicRecord,
        execution_reporter:execution.publicRecord
      }
    }
  };
}
function readSigner(trust, role) {
  const record=trust.trusted_signers && trust.trusted_signers[role];
  check(record && typeof record.public_key_spki_base64 === "string",
        "Missing independently pinned public key for " + role);
  const encoded=record.public_key_spki_base64;
  const der=Buffer.from(encoded,"base64");
  check(der.length>0 && der.toString("base64")===encoded,
        "Invalid public key encoding for " + role);
  check(record.key_id===keyId(der),"Incorrect signer key identifier");
  const publicKey=crypto.createPublicKey({key:der,format:"der",type:"spki"});
  check(publicKey.asymmetricKeyType==="ed25519","Only Ed25519 test signers accepted");
  return {publicKey,der:encoded};
}
function verifyDemo(receipt,trust) {
  check(receipt && receipt.schema===SCHEMA && receipt.synthetic_only===true,
        "Not a synthetic RAAA evidence specimen");
  check(receipt.trust_statement ===
        "Signed records of fictional assertions; NOT proof that an actual authorized action occurred.",
        "Synthetic evidence caveat missing");
  check(trust && trust.schema===SCHEMA && trust.synthetic_only===true &&
        trust.issuer==="locally-generated-ephemeral-test-keys-not-Privi-production",
        "Expected separately supplied local test trust roots");
  const signers=ROLES.map(role=>readSigner(trust,role));
  check(signers[0].der!==signers[1].der,"Authorization and execution require distinct test signers");
  check(Array.isArray(receipt.events) && receipt.events.length===2,
        "Expected exactly one decision and one execution report; no gaps");
  const [decision,outcome]=receipt.events;
  const expected=[
    {kind:"authorization_decision",role:ROLES[0],result:"allow",sequence:1},
    {kind:"execution_report",role:ROLES[1],result:"reported_success",sequence:2}
  ];
  for(let i=0;i<2;i++) {
    const e=receipt.events[i], want=expected[i];
    check(e && typeof e==="object" && !Array.isArray(e),"Invalid event");
    check(e.sequence===want.sequence && e.kind===want.kind &&
          e.signer_role===want.role && e.result===want.result,
          "Missing, reordered, or unexpected event");
    check(typeof e.event_id==="string" && e.event_id.startsWith("event-SYNTHETIC-"),
          "Event must be a clearly marked synthetic record");
    check(typeof e.entry_hash==="string" && /^[0-9a-f]{64}$/.test(e.entry_hash) &&
          e.entry_hash===hashEvent(e),"Event hash mismatch or tampering");
    const signature=Buffer.from(e.signature_b64||"","base64");
    check(signature.length===64 && signature.toString("base64")===e.signature_b64 &&
          crypto.verify(null,Buffer.from(e.entry_hash,"hex"),signers[i].publicKey,signature),
          "Invalid " + want.role + " signature");
    for(const field of SHARED) {
      check(typeof e[field]==="string" && e[field].length>0,
            "Missing required authorization/execution binding: " + field);
    }
    check(e.approval_evidence_type==="reference-only-not-human-verified",
          "Synthetic approval must not imply human verification");
    check(typeof e.software_version==="string" && e.software_version.length>0,
          "Missing deployed software version");
    check(typeof e.occurred_at==="string" && Number.isFinite(Date.parse(e.occurred_at)),
          "Invalid recorded event timestamp");
  }
  for(const field of SHARED) {
    check(decision[field]===outcome[field],"Authorization and execution mismatch: " + field);
  }
  check(decision.event_id!==outcome.event_id,"Replay: repeated event identifier");
  check(decision.previous_entry_hash===ZERO,"Decision does not start a clean synthetic chain");
  check(outcome.previous_entry_hash===decision.entry_hash &&
        outcome.authorization_entry_hash===decision.entry_hash,
        "Execution not linked to signed authorization");
  check(Date.parse(outcome.occurred_at)>Date.parse(decision.occurred_at),
        "Execution reported before authorization");
  check(typeof outcome.external_ack_id==="string" &&
        outcome.external_ack_id.startsWith("ACK-SYNTHETIC-"),
        "Missing synthetic external acknowledgment reference");
  check(receipt.head_hash===outcome.entry_hash,"Evidence chain head mismatch");
  return {
    valid:true,synthetic_only:true,verified_signatures:2,
    chain_head:receipt.head_hash,
    execution_proven:false,
    note:"Cryptography verifies locally signed assertions, not real execution or policy correctness."
  };
}
function readJson(file) {
  return JSON.parse(fs.readFileSync(file,"utf8"));
}
function main(argv) {
  if (argv[0]==="create" && argv.length===2) {
    const dest=path.resolve(argv[1]);
    fs.mkdirSync(dest,{recursive:true,mode:0o700});
    const {receipt,trust}=makeDemo();
    // No private key material is serialized or persisted.
    fs.writeFileSync(path.join(dest,"receipt.json"),JSON.stringify(receipt,null,2)+"\n",
                     {flag:"wx",mode:0o600});
    fs.writeFileSync(path.join(dest,"trusted-keys.json"),JSON.stringify(trust,null,2)+"\n",
                     {flag:"wx",mode:0o600});
    console.log("Created synthetic receipt + test public keys in " + dest);
    console.log("Test signer fingerprints must be pinned independently in any real evaluation.");
    return;
  }
  if(argv[0]==="verify" && argv.length===3) {
    const result=verifyDemo(readJson(argv[1]),readJson(argv[2]));
    console.log("PASS " + result.verified_signatures + " synthetic signatures and event linkage");
    console.log("NOT PROVEN: real action execution, human approval, tenant authentication or compliance");
    return;
  }
  throw Error("Usage: node demo.cjs create <new-output-folder> | verify <receipt.json> <trusted-keys.json>");
}
if(require.main===module) {
  try { main(process.argv.slice(2)); }
  catch (err) {console.error("FAIL: " + err.message);process.exitCode=1;}
}
module.exports={makeDemo,verifyDemo,hashEvent,canonical};
