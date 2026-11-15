// Copyright (c) 2026 Privi World Corp. All rights reserved.
// Guarded EIP-7702 Base USDC paymaster prototype. NOT the production PRVA verifier.
import process from "node:process";

export const BASE_CHAIN_ID = 8453;
export const BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
export const EIP7702_IMPLEMENTATION = "0xe6Cae83BdE06E4c305530e199D7217f42808555B";
export const DATA_SINK = "0x000000000000000000000000000000000000dEaD";
export const PRVA_PREFIX = "0x5052564101";
const ROOT = /^(?:0x)?[0-9a-fA-F]{64}$/;

export function anchorData(root) {
  if (typeof root !== "string" || !ROOT.test(root)) {
    throw new Error("Expected exactly one 32-byte SHA-256 root, optionally 0x-prefixed");
  }
  return PRVA_PREFIX + root.replace(/^0x/i, "").toLowerCase();
}

export function validateOptions(opts = {}) {
  const root = String(opts.root || "");
  const mode = String(opts.mode || "usdc");
  if (!["usdc", "sponsored"].includes(mode)) throw new Error("Mode must be 'usdc' or 'sponsored'");
  return {
    root: anchorData(root).slice(PRVA_PREFIX.length),
    mode,
    calldata: anchorData(root),
    chainId: BASE_CHAIN_ID,
    network: "Base",
    usdcContract: BASE_USDC,
    to: DATA_SINK,
    proofVersion: "prva-userop-v1",
    note: "This is a different onchain proof transport than legacy Privi Anchor: verify a successful UserOperation and its included execution calldata before treating it as an external anchor."
  };
}

async function submit(opts, env) {
  // Never EIP-7702-delegate a service EOA or spend USDC merely by running the script.
  if (env.PRIVI_USDC_ANCHOR_EXECUTE !== "1" || env.PRIVI_USDC_ANCHOR_EIP7702_APPROVED !== "1") {
    throw new Error("Explicit opt-in required: PRIVI_USDC_ANCHOR_EXECUTE=1 and PRIVI_USDC_ANCHOR_EIP7702_APPROVED=1");
  }
  const key = (env.ANCHOR_PRIVATE_KEY || "").trim();
  const apiKey = (env.PIMLICO_API_KEY || "").trim();
  if (!/^0x[0-9a-fA-F]{64}$/.test(key) || !apiKey) {
    throw new Error("ANCHOR_PRIVATE_KEY and mainnet-enabled PIMLICO_API_KEY must be configured privately");
  }
  if (opts.mode === "sponsored" && !env.PIMLICO_SPONSORSHIP_POLICY_ID) {
    throw new Error("Sponsor mode requires an owner-controlled sponsorship policy with strict spend and target limits");
  }

  const [
    { createSmartAccountClient },
    { to7702SimpleSmartAccount },
    { createPimlicoClient },
    { prepareUserOperationForErc20Paymaster },
    { createPublicClient, http, erc20Abi },
    { entryPoint08Address },
    { privateKeyToAccount },
    { base },
  ] = await Promise.all([
    import("permissionless"),
    import("permissionless/accounts"),
    import("permissionless/clients/pimlico"),
    import("permissionless/experimental/pimlico"),
    import("viem"),
    import("viem/account-abstraction"),
    import("viem/accounts"),
    import("viem/chains"),
  ]);

  const publicClient = createPublicClient({
    chain: base, transport: http(env.ANCHOR_RPC_URL || "https://mainnet.base.org"),
  });
  const realChainId = await publicClient.getChainId();
  if (realChainId !== BASE_CHAIN_ID) throw new Error("RPC chain ID mismatch; refusing signature");

  const signer = privateKeyToAccount(key);
  const account = await to7702SimpleSmartAccount({ client: publicClient, owner: signer });
  const balance = await publicClient.readContract({
    address: BASE_USDC,
    abi: erc20Abi,
    functionName: "balanceOf",
    args: [account.address],
  });
  if (opts.mode === "usdc" && balance === 0n) {
    throw new Error("The Anchor EOA has no Base USDC. Use an approved sponsored paymaster policy instead; no transaction sent.");
  }

  const bundlerUrl = `https://api.pimlico.io/v2/${BASE_CHAIN_ID}/rpc?apikey=${encodeURIComponent(apiKey)}`;
  const pimlicoClient = createPimlicoClient({
    chain: base,
    transport: http(bundlerUrl),
    entryPoint: { address: entryPoint08Address, version: "0.8" },
  });
  const client = createSmartAccountClient({
    account, chain: base,
    bundlerTransport: http(bundlerUrl),
    paymaster: pimlicoClient,
    userOperation: {
      estimateFeesPerGas: async () => (await pimlicoClient.getUserOperationGasPrice()).fast,
      prepareUserOperation: prepareUserOperationForErc20Paymaster(pimlicoClient),
    },
  });
  const hasDelegation = await account.isDeployed();
  // Authorization is a persistent change to this service's EOA! It is never implicit.
  const authorization = hasDelegation ? undefined : await signer.signAuthorization({
    address: EIP7702_IMPLEMENTATION,
    chainId: BASE_CHAIN_ID,
    nonce: await publicClient.getTransactionCount({ address: signer.address }),
  });
  const context = opts.mode === "usdc"
    ? { token: BASE_USDC }
    : { sponsorshipPolicyId: env.PIMLICO_SPONSORSHIP_POLICY_ID };
  const hash = await client.sendUserOperation({
    calls: [{ to: DATA_SINK, value: 0n, data: opts.calldata }],
    paymasterContext: context,
    authorization,
  });
  const receipt = await client.waitForUserOperationReceipt({ hash, timeout: 60_000 });
  const txHash = receipt?.receipt?.transactionHash;
  if (!receipt?.success || !/^0x[0-9a-fA-F]{64}$/.test(String(txHash))) {
    throw new Error("UserOperation not confirmed successful; inspect the signed UserOp before retrying to avoid double charging");
  }
  return {
    status: "confirmed_user_operation",
    chain_id: BASE_CHAIN_ID,
    anchor_wallet: signer.address,
    merkle_root: opts.root,
    calldata: opts.calldata,
    tx_hash: txHash,
    user_op_hash: hash,
    fee_mode: opts.mode === "usdc" ? "paymaster_charges_Base_USDC" : "paymaster_sponsored",
    proof_version: "prva-userop-v1",
    compatible_with_legacy_anchor_verify: false,
    note: "Do not call this a legacy Privi Anchor proof; deploy an independent ERC-4337 calldata verifier before using it for customer receipts."
  };
}

export async function main(argv = process.argv.slice(2), env = process.env) {
  try {
    const index = argv.findIndex(arg => arg === "--root");
    if (index < 0 || index + 1 >= argv.length) throw new Error("Usage: node anchor.mjs --root <sha256> [--mode usdc|sponsored] [--execute]");
    const modeIndex = argv.findIndex(arg => arg === "--mode");
    if (modeIndex >= 0 && modeIndex + 1 >= argv.length) throw new Error("Missing --mode value");
    const options = validateOptions({
      root: argv[index + 1],
      mode: modeIndex >= 0 ? argv[modeIndex + 1] : "usdc",
    });
    if (!argv.includes("--execute")) {
      process.stdout.write(JSON.stringify({ ...options, status: "dry_run", transaction_sent: false }, null, 2) + "\n");
      return 0;
    }
    const result = await submit(options, env);
    process.stdout.write(JSON.stringify(result, null, 2) + "\n");
    return 0;
  } catch (e) {
    process.stderr.write(JSON.stringify({ status: "not_confirmed", error: String(e?.message || e),
      warn: "No successful transaction has been established by this run" }) + "\n");
    return 1;
  }
}

if (process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href) {
  process.exitCode = await main();
}
