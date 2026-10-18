#!/usr/bin/env node
"use strict";
/*
 * On a disposable GitHub Actions runner only, sign and send one *valueless*
 * upstream Cosmos EVM local-4221/262144 native atest transfer. The signing
 * key is exported IN MEMORY from the generated test keyring and never printed.
 * Never run this with any real wallet, persistent chain or PRVI/BNB PRIV.
 */
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

function invariant(test, message) { if (!test) throw new Error(message); }
function localGate(environment, url) {
  invariant(environment.CI === "true" &&
    environment.PRIVI_EPHEMERAL_TRANSFER_TEST === "1",
    "CI-only local disposable TEST transfer opt-in missing");
  invariant(url === "http://127.0.0.1:8545", "only localhost dev EVM RPC allowed");
}
function exportDevKey(ephemeralRoot) {
  invariant(path.basename(ephemeralRoot) === ".upstream-evm",
    "unsafe export attempted outside disposable upstream directory");
  const home = path.join(ephemeralRoot, ".testnets", "node0", "evmd");
  // GitHub runner user cannot traverse .testnets (0700, Docker uid 1025).
  // Check through the disposable container instead; never chmod secrets or
  // export validator key files to the runner.
  invariant(fs.existsSync(path.join(ephemeralRoot, ".testnets")),
    "disposable testnet directory not present");
  execFileSync("docker",
    ["run", "--rm", "--entrypoint", "/bin/sh",
     "-v", home + ":/data:ro", "cosmos/evmd",
     "-ec", "test -r /data/config/genesis.json"],
    {encoding:"utf8", timeout:30000, stdio:["ignore","pipe","pipe"]});
  const result = execFileSync("docker",
    ["run", "--rm", "-v", home + ":/data:ro", "cosmos/evmd",
     "keys", "unsafe-export-eth-key", "account0",
     "--keyring-backend", "test", "--home", "/data"],
    {encoding: "utf8", timeout: 30000, stdio:["ignore","pipe","pipe"]});
  const key = result.trim();
  invariant(/^[0-9A-Fa-f]{64}$/.test(key),
    "upstream disposable account0 key export returned invalid format");
  return "0x" + key;
}
async function run(env = process.env) {
  const rpc = "http://127.0.0.1:8545";
  localGate(env, rpc);
  const modulePath = env.PRIVI_ETHERS_MODULE_PATH;
  invariant(modulePath && modulePath.includes("privi-test-ethers"),
    "require isolated, disposable pinned ethers installation");
  const {ethers} = require(modulePath);
  const root = path.resolve(__dirname, "..", ".upstream-evm");
  const provider = new ethers.JsonRpcProvider(rpc, {name:"privi-disposable-dev",chainId:262144},
                                            {staticNetwork:true});
  const observedId = await provider.send("eth_chainId", []);
  invariant(BigInt(observedId) === 262144n, "refusing to sign on unexpected EVM chain ID");
  const key = exportDevKey(root);
  const wallet = new ethers.Wallet(key, provider);
  const currentBalance = await provider.getBalance(wallet.address);
  const amountWei = 10000000000000n; // 0.00001 valueless TEST
  const gasPrice = 10000000000n;     // local disposable chain only
  const gasLimit = 30000n;
  invariant(currentBalance >= gasPrice * gasLimit + amountWei,
    "disposable account0 needs funded atest genesis fixture before signing");
  // A fresh receiver exists only in memory, receives valueless atest and
  // gets thrown away when the GitHub runner is destroyed.
  const recipient = ethers.Wallet.createRandom().address;
  const before = await provider.getBalance(recipient);
  invariant(before === 0n, "unexpected pre-funded throwaway receiver");
  const tx = await wallet.sendTransaction({
    to:recipient, value:amountWei,gasLimit,gasPrice,chainId:262144,type:0,
    data:"0x"
  });
  invariant(/^0x[0-9a-f]{64}$/i.test(tx.hash), "broadcast returned invalid tx hash");
  const receipt = await tx.wait(2, 120000);
  invariant(receipt && receipt.status === 1, "transaction never mined successfully");
  const got = await provider.getBalance(recipient);
  invariant(got-before === amountWei,
    "recipient balance delta not equal to transmitted valueless native value");
  const afterSender=await provider.getBalance(wallet.address);
  invariant(afterSender<currentBalance,
    "sender balance did not decrease");
  // Verify independently through a separate process using eth_* JSON-RPC,
  // checking transaction sender, receiver, amount, block and confirmations.
  const raw = execFileSync("python3",[
    path.join(__dirname, "evm_receipt_audit.py"),
    "--rpc",rpc,"--expect-chain","262144",
    "--tx-hash",tx.hash,"--sender",wallet.address,"--recipient",recipient,
    "--value-wei",amountWei.toString(),"--min-confirmations","2"
  ],{encoding:"utf8",timeout:30000});
  const audit = JSON.parse(raw);
  invariant(audit.ok===true && audit.tx_hash.toLowerCase()===tx.hash.toLowerCase(),
    "independent mined-receipt auditor did not confirm transaction");
  console.log(JSON.stringify({
    status:"REAL_DISPOSABLE_LOCAL_TEST_TRANSFER_VERIFIED",
    network:"local-4221",evm_chain_id:262144,asset:"atest (valueless developer TEST only)",
    tx_hash:tx.hash,from:wallet.address,to:recipient,value_wei:amountWei.toString(),
    block_number:receipt.blockNumber,confirmations:audit.confirmations,
    recipient_delta_wei:(got-before).toString(),
    receipt_audit:"PASS",
    limitations:"Same-runner upstream demo: no public network, independent validators, audited PRVI issuance or mainnet authorization"
  },null,2));
}
if (require.main === module) {
  run().catch(error => {
    // Never dump subprocess stderr or potentially sensitive arguments/objects.
    console.error("Disposable dev TEST transfer FAILED: " + (error && error.shortMessage
      ? error.shortMessage : error && error.message ? String(error.message).slice(0,280)
      : "unknown error"));
    process.exitCode=1;
  });
}
module.exports={localGate,exportDevKey};
