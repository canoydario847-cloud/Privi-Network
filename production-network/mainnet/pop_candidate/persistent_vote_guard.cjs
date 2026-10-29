"use strict";
/*
 * RESEARCH ONLY: local crash-resistant equivocation guard for proposed Privi
 * Point of Position validator vote signatures.
 *
 * This is not a running consensus engine, does not communicate over network,
 * and provides NO actual PoP blockchain finality. A separate signed state
 * machine, finalized position proofs and non-stake proposer rules are needed.
 *
 * Safety boundary: an honest validator may not precommit conflicting block
 * hashes OR parent links at the same {chain,genesis,height}, even in different rounds.
 * Reserve the block on durable LOCAL filesystem before releasing a signature.
 *
 * Assumptions NOT satisfied by itself:
 * secure local filesystem + exclusive host key custody; fsync is supported;
 * no malicious administrator editing files; complete data synchronization;
 * no networked or shared FS; no adversarial runtime; no safe unlock/rotation;
 * no crash-consistent consensus view-change, availability or fork-choice.
 */
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {
  hash,signedMessage,verifyProposal,voteFields,TRUSTED_MODE
} = require("./engine.cjs");

const HEX = /^0x[0-9a-f]{64}$/;
function must(x, why) { if (!x) throw Error(why); }
function safeInt(x, label) {
  must(Number.isSafeInteger(x) && x>=1, "Invalid " + label);
}
function strictLocalDirectory(dir) {
  must(typeof dir==="string" && path.isAbsolute(dir), "Absolute local research lock path required");
  // Refuse symlinked ancestors: checking only the final directory is insufficient.
  let ancestor=path.parse(dir).root;
  for (const component of path.relative(ancestor,dir).split(path.sep).filter(Boolean)) {
    ancestor=path.join(ancestor,component);
    must(!fs.lstatSync(ancestor).isSymbolicLink(),
         "Local lock directory path must not contain symlinks");
  }
  const stat = fs.lstatSync(dir);
  must(stat.isDirectory() && !stat.isSymbolicLink(), "Local lock directory must not be symlink");
  must((stat.mode & 0o077) === 0, "Local lock directory must be owner-only (0700)");
  return fs.realpathSync(dir);
}
function recordFor(committee, height, validatorId, blockHash, previousBlockHash) {
  must(committee?.mode === TRUSTED_MODE, "PoP validator lock is RESEARCH ONLY");
  must(typeof committee.chainId==="string" && committee.chainId.startsWith("privi-pop-research-"),
       "Native Privi research identity required");
  must(typeof committee.genesisHash==="string" && HEX.test(committee.genesisHash),
       "Pinned research genesis required");
  safeInt(committee.epoch,"PoP epoch");
  safeInt(height,"PoP height");
  must(typeof validatorId==="string" && HEX.test(validatorId) &&
       committee.byId?.has(validatorId),"Voter is not an admitted PoP signer");
  must(typeof blockHash==="string" && HEX.test(blockHash), "Invalid PoP candidate block hash");
  must(typeof previousBlockHash==="string" && HEX.test(previousBlockHash) &&
       previousBlockHash!==blockHash, "Invalid PoP previous-block hash commitment");
  return {
    format:"PriviPoPResearchHeightLock/v2", chainId:committee.chainId,
    genesisHash:committee.genesisHash,epoch:committee.epoch,
    height,validatorId,blockHash,previousBlockHash
  };
}
function lockedFileName(record) {
  // Domain transitions cannot make a signer forget a previous commitment
  // at the SAME height. Lock across membership epochs for the same chain
  // and genesis; any epoch mismatch fails closed unless a future formally
  // reviewed joint-consensus transition explicitly handles signer recovery.
  const key = [record.chainId,record.genesisHash,record.height,record.validatorId];
  return hash(Buffer.from(JSON.stringify(key),"utf8")).slice(2) + ".json";
}
function syncLockDirectory(location) {
  const rootFd=fs.openSync(location,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY);
  try {fs.fsyncSync(rootFd);} finally {fs.closeSync(rootFd);}
}
function reservePosition(dir, committee, height, validatorId, blockHash, previousBlockHash) {
  const location = strictLocalDirectory(dir);
  const record = recordFor(committee,height,validatorId,blockHash,previousBlockHash);
  const file=path.join(location,lockedFileName(record));
  let fd;
  try {
    fd=fs.openSync(file,
      fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_WRONLY|fs.constants.O_NOFOLLOW,
      0o600);
  } catch (e) {
    if (e.code !== "EEXIST") throw e;
    // Existing lock is ALWAYS immutable: corrupt/unparseable locks block
    // further signing. Open the inode without following symlinks, verify the
    // inode itself, and never trust a separately reopened pathname.
    // A hostile/corrupt lock path might be a FIFO: O_RDONLY alone can block
    // forever before fstatSync can reject it. Never block the signer on open.
    const oldFd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|
                                   fs.constants.O_NONBLOCK);
    try {
      const stat=fs.fstatSync(oldFd);
      must(stat.isFile() && stat.size>0 && stat.size<=2048 &&
           (stat.mode & 0o077)===0 && stat.nlink===1,
           "PoP height lock corrupt, hard-linked or insecure; refuse to sign");
      let old, original;
      try {
        original=fs.readFileSync(oldFd);
        old=JSON.parse(original.toString("utf8"));
      }
      catch (_) {throw Error("PoP height lock corrupt; refuse to sign");}
      for (const field of Object.keys(record)) {
        must(old[field]===record[field],
             field==="blockHash" ? "PoP equivocation: conflicting block at locked height" :
           field==="previousBlockHash" ? "PoP equivocation: conflicting parent at locked height" :
             "PoP existing height lock corrupt or inconsistent");
      }
      must(Object.keys(old).length===Object.keys(record).length,
           "PoP height lock unexpected data");
      // JSON.parse silently accepts duplicate field names and alternative
      // encodings, masking an earlier forged field behind the later one.
      // The guard may replay ONLY the precise bytes this signer writes.
      // This conservatively rejects reordered, duplicated or extra fields.
      const canonical=Buffer.from(JSON.stringify(record)+"\n","utf8");
      must(original.equals(canonical),
           "PoP height lock corrupt or noncanonical; refuse to sign");
      // A previous attempt may have failed during fsync. Never release a
      // replayed signature until the file and directory are both durable.
      fs.fsyncSync(oldFd);
    } finally {
      fs.closeSync(oldFd);
    }
    syncLockDirectory(location);
    return Object.freeze({alreadyReserved:true,blockHash});
  }
  let completed=false;
  try {
    const body=Buffer.from(JSON.stringify(record)+"\n","utf8");
    must(body.length<=2048, "PoP local height lock too large");
    let pos=0;
    while (pos<body.length) {
      const written=fs.writeSync(fd,body,pos,body.length-pos,pos);
      must(written>0, "PoP lock write failed");
      pos+=written;
    }
    fs.fsyncSync(fd);
    completed=true;
  } finally {
    fs.closeSync(fd);
  }
  // On I/O errors we *retain* the broken file and fail closed. The
  // operator must recover from backed-up signing-state under a new audit.
  must(completed,"PoP lock was not durable");
  syncLockDirectory(location);
  return Object.freeze({alreadyReserved:false,blockHash});
}

function signCommitWithResearchLock({lockDirectory,committee,proposal,privateKey}) {
  const fields=verifyProposal(committee,proposal);
  must(privateKey && privateKey.type==="private" &&
       privateKey.asymmetricKeyType==="ed25519","PoP Ed25519 key required");
  const der=crypto.createPublicKey(privateKey).export({type:"spki",format:"der"});
  const validatorId=hash(der);
  must(committee.byId.has(validatorId),"Private key is not a registered PoP validator");
  const height=proposal.height;
  // No signature may escape before local fsync is complete.
  reservePosition(lockDirectory,committee,height,validatorId,
                  proposal.blockHash,proposal.previousBlockHash);
  const bytes=signedMessage("commit",voteFields(fields,validatorId));
  return {
    validatorId,
    signature:crypto.sign(null,bytes,privateKey).toString("base64"),
    researchOnly:true
  };
}
module.exports={recordFor,lockedFileName,reservePosition,signCommitWithResearchLock};
