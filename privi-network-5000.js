// Privi Network v0.1
// Single-validator signed-record blockchain prototype.
// Node.js 20+; no npm dependencies.
// No financial transactions or PRIV bridging.
"use strict";
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const CHAIN_ID = "privi-dev-1";
const HOST = process.env.PRIVI_HOST || "0.0.0.0";
const PORT = Number(process.env.PORT || process.env.PRIVI_PORT || 8787);
const DIR = process.env.RAILWAY_VOLUME_MOUNT_PATH || path.join(__dirname, "privi-data");
const CHAIN_PATH = path.join(DIR, "chain.json");
const VAL_PATH = path.join(DIR, "validator.pem");
const WALLET_PATH = path.join(DIR, "user-wallet.pem");
const EXPLORER_PATH = path.join(__dirname, "privi-explorer.html");
const MAX_PENDING = 200;

const sha = x =>
  crypto.createHash("sha256").update(x).digest("hex");
const pubDer = key =>
  crypto.createPublicKey(key).export({
    format: "der",
    type: "spki"
  });
const addr = publicKey =>
  "prv_" +
  sha(Buffer.from(publicKey, "base64")).slice(0, 40);
const safePub = publicKey =>
  crypto.createPublicKey({
    key: Buffer.from(publicKey, "base64"),
    format: "der",
    type: "spki"
  });

function makeKey(file) {
  fs.mkdirSync(DIR, {
    recursive: true,
    mode: 0o700
  });
  if (!fs.existsSync(file)) {
    const pair = crypto.generateKeyPairSync("ed25519");
    fs.writeFileSync(
      file,
      pair.privateKey.export({
        format: "pem",
        type: "pkcs8"
      }),
      { mode: 0o600, flag: "wx" }
    );
  }
  return crypto.createPrivateKey(
    fs.readFileSync(file)
  );
}

const pub64 = key =>
  pubDer(key).toString("base64");

function signingFields(tx) {
  return {
    chainId: tx.chainId,
    from: tx.from,
    nonce: tx.nonce,
    kind: tx.kind,
    payload: tx.payload,
    publicKey: tx.publicKey,
    timestamp: tx.timestamp
  };
}

function transactionID(tx) {
  return sha(JSON.stringify({
    ...signingFields(tx),
    signature: tx.signature
  }));
}

function verifyTx(tx) {
  if (
    !tx ||
    typeof tx !== "object" ||
    Array.isArray(tx)
  ) return false;
  if (
    tx.chainId !== CHAIN_ID ||
    tx.kind !== "NOTE" ||
    typeof tx.payload !== "string" ||
    tx.payload.length < 1 ||
    Buffer.byteLength(tx.payload) > 2000
  ) return false;
  if (
    !Number.isSafeInteger(tx.nonce) ||
    tx.nonce < 1 ||
    !Number.isSafeInteger(tx.timestamp) ||
    typeof tx.publicKey !== "string" ||
    typeof tx.signature !== "string"
  ) return false;
  try {
    if (
      tx.from !== addr(tx.publicKey) ||
      tx.id !== transactionID(tx)
    ) return false;
    return crypto.verify(
      null,
      Buffer.from(
        JSON.stringify(signingFields(tx))
      ),
      safePub(tx.publicKey),
      Buffer.from(tx.signature, "base64")
    );
  } catch {
    return false;
  }
}

// Merkle root of the transaction IDs.
function root(ids) {
  if (ids.length === 0) return sha("");
  let layer = ids.slice();
  while (layer.length > 1) {
    const next = [];
    for (let i = 0; i < layer.length; i += 2) {
      next.push(
        sha(layer[i] + (layer[i + 1] || layer[i]))
      );
    }
    layer = next;
  }
  return layer[0];
}

function core(b) {
  return {
    index: b.index,
    chainId: b.chainId,
    timestamp: b.timestamp,
    previousHash: b.previousHash,
    merkleRoot: b.merkleRoot,
    validator: b.validator,
    transactions: b.transactions
  };
}

const blockHash = b =>
  sha(JSON.stringify(core(b)));

// Deterministic genesis block.
const genesis = (() => {
  const g = {
    index: 0,
    chainId: CHAIN_ID,
    timestamp: 0,
    previousHash: "0".repeat(64),
    merkleRoot: root([]),
    validator: "GENESIS",
    transactions: []
  };
  g.hash = blockHash(g);
  g.signature = "";
  return g;
})();

// Verify stored blocks, validator signatures,
// transaction signatures and nonce ordering.
function checkChain(chain, validatorPub) {
  if (
    !Array.isArray(chain) ||
    !chain.length ||
    chain[0].hash !== genesis.hash ||
    JSON.stringify(chain[0]) !== JSON.stringify(genesis)
  ) {
    throw Error("Invalid genesis block");
  }
  const used = new Map();
  for (let i = 1; i < chain.length; i++) {
    const b = chain[i];
    const prev = chain[i - 1];
    if (
      b.index !== i ||
      b.chainId !== CHAIN_ID ||
      b.previousHash !== prev.hash ||
      !Number.isSafeInteger(b.timestamp) ||
      b.timestamp < prev.timestamp ||
      b.validator !== addr(validatorPub) ||
      !Array.isArray(b.transactions) ||
      b.transactions.length > 100 ||
      b.merkleRoot !== root(
        b.transactions.map(t => t.id)
      ) ||
      b.hash !== blockHash(b)
    ) {
      throw Error("Invalid block " + i);
    }
    const validatorValid = crypto.verify(
      null,
      Buffer.from(b.hash, "hex"),
      safePub(validatorPub),
      Buffer.from(b.signature, "base64")
    );
    if (!validatorValid) {
      throw Error(
        "Invalid validator signature at " + i
      );
    }
    for (const tx of b.transactions) {
      const expectedNonce =
        (used.get(tx.from) || 0) + 1;
      if (
        !verifyTx(tx) ||
        tx.nonce !== expectedNonce
      ) {
        throw Error(
          "Invalid transaction in block " + i
        );
      }
      used.set(tx.from, tx.nonce);
    }
  }
  return used;
}

function save(chain) {
  const temp = CHAIN_PATH + ".tmp";
  fs.writeFileSync(
    temp,
    JSON.stringify(chain, null, 2),
    { mode: 0o600 }
  );
  fs.renameSync(temp, CHAIN_PATH);
}

// Developer commands: keygen, send, verify.
async function cli() {
  const cmd = process.argv[2];
  if (cmd === "keygen") {
    const key = makeKey(WALLET_PATH);
    console.log(
      "Wallet:", addr(pub64(key)),
      "\nPrivate key file:", WALLET_PATH,
      "\nNever share this file."
    );
    return true;
  }
  if (cmd === "send") {
    const payload = process.argv
      .slice(3).join(" ").trim();
    if (
      !payload ||
      Buffer.byteLength(payload) > 2000
    ) {
      throw Error(
        "Supply 1–2000 bytes of note text"
      );
    }
    if (!fs.existsSync(WALLET_PATH)) {
      throw Error(
        "Run: node privi-network-5000.js keygen"
      );
    }
    const key = crypto.createPrivateKey(
      fs.readFileSync(WALLET_PATH)
    );
    const publicKey = pub64(key);
    const from = addr(publicKey);
    const response = await fetch(
      `http://127.0.0.1:${PORT}/api/account/${from}`
    );
    const account = await response.json();
    const tx = {
      chainId: CHAIN_ID,
      from,
      nonce: account.nextNonce,
      kind: "NOTE",
      payload,
      publicKey,
      timestamp: Date.now()
    };
    tx.signature = crypto.sign(
      null,
      Buffer.from(
        JSON.stringify(signingFields(tx))
      ),
      key
    ).toString("base64");
    tx.id = transactionID(tx);
    const resultResponse = await fetch(
      `http://127.0.0.1:${PORT}/api/tx`,
      {
        method: "POST",
        headers: {
          "content-type": "application/json"
        },
        body: JSON.stringify(tx)
      }
    );
    const result = await resultResponse.json();
    if (!resultResponse.ok) {
      throw Error(JSON.stringify(result));
    }
    console.log(
      "Submitted:", tx.id,
      "\nExplorer:",
      `http://127.0.0.1:${PORT}/`
    );
    return true;
  }
  if (cmd === "verify") {
    if (
      !fs.existsSync(CHAIN_PATH) ||
      !fs.existsSync(VAL_PATH)
    ) {
      throw Error("No local chain");
    }
    const key = crypto.createPrivateKey(
      fs.readFileSync(VAL_PATH)
    );
    const chain = JSON.parse(
      fs.readFileSync(CHAIN_PATH, "utf8")
    );
    checkChain(chain, pub64(key));
    console.log(
      "VALID:", chain.length, "blocks"
    );
    return true;
  }
  return false;
}

async function start() {
  const key = makeKey(VAL_PATH);
  const validatorPub = pub64(key);
  const validator = addr(validatorPub);
  let chain = fs.existsSync(CHAIN_PATH)
    ? JSON.parse(
      fs.readFileSync(CHAIN_PATH, "utf8")
    )
    : [genesis];
  let nonces = checkChain(chain, validatorPub);
  if (!fs.existsSync(CHAIN_PATH)) {
    save(chain);
  }
  let pending = [];

  function nextNonce(address) {
    let n = nonces.get(address) || 0;
    for (const tx of pending) {
      if (
        tx.from === address &&
        tx.nonce > n
      ) {
        n = tx.nonce;
      }
    }
    return n + 1;
  }

  function produce() {
    if (!pending.length) return;
    const txs = pending.splice(0, 100);
    const previous = chain[chain.length - 1];
    const b = {
      index: chain.length,
      chainId: CHAIN_ID,
      timestamp: Math.max(
        Date.now(), previous.timestamp
      ),
      previousHash: previous.hash,
      merkleRoot: root(txs.map(t => t.id)),
      validator,
      transactions: txs
    };
    b.hash = blockHash(b);
    b.signature = crypto.sign(
      null,
      Buffer.from(b.hash, "hex"),
      key
    ).toString("base64");
    const updated = [...chain, b];
    const newNonces = checkChain(
      updated, validatorPub
    );
    save(updated);
    chain = updated;
    nonces = newNonces;
    console.log(
      "Block", b.index,
      b.hash.slice(0, 16),
      txs.length, "signed records"
    );
  }

  function json(res, status, obj) {
    res.writeHead(status, {
      "content-type":
        "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff"
    });
    res.end(JSON.stringify(obj));
  }

  const server = http.createServer(async (req, res) => {
    const u = new URL(
      req.url, "http://localhost"
    );

    if (
      req.method === "GET" &&
      u.pathname === "/"
    ) {
      if (!fs.existsSync(EXPLORER_PATH)) {
        return json(res, 404, {
          error: "Explorer file missing"
        });
      }
      res.writeHead(200, {
        "content-type":
          "text/html; charset=utf-8",
        "content-security-policy":
          "default-src 'self'; " +
          "script-src 'self' 'unsafe-inline'; " +
          "style-src 'self' 'unsafe-inline'",
        "x-content-type-options": "nosniff"
      });
      res.end(
        fs.readFileSync(EXPLORER_PATH)
      );
      return;
    }

    if (
      req.method === "GET" &&
      u.pathname === "/api/status"
    ) {
      return json(res, 200, {
        chainId: CHAIN_ID,
        network: "Privi single-validator developer network",
        height: chain.length - 1,
        latestHash: chain.at(-1).hash,
        validator,
        transactions: chain.reduce(
          (n, b) => n + b.transactions.length, 0
        ),
        pending: pending.length
      });
    }

    if (
      req.method === "GET" &&
      u.pathname === "/api/blocks"
    ) {
      return json(
        res, 200,
        chain.slice(-30).reverse().map(
          b => ({
            ...b,
            transactions: b.transactions.map(
              t => ({
                id: t.id,
                from: t.from,
                kind: t.kind
              })
            )
          })
        )
      );
    }

    let match = u.pathname.match(
      /^\/api\/block\/(\d+)$/
    );
    if (req.method === "GET" && match) {
      return json(
        res, 200,
        chain[Number(match[1])] || {
          error: "Not found"
        }
      );
    }

    match = u.pathname.match(
      /^\/api\/tx\/([a-f0-9]{64})$/
    );
    if (req.method === "GET" && match) {
      for (const b of chain) {
        const tx = b.transactions.find(
          t => t.id === match[1]
        );
        if (tx) {
          return json(res, 200, {
            block: b.index,
            transaction: tx
          });
        }
      }
      return json(res, 404, {
        error: "Transaction not found"
      });
    }

    match = u.pathname.match(
      /^\/api\/account\/(prv_[a-f0-9]{40})$/
    );
    if (req.method === "GET" && match) {
      return json(res, 200, {
        address: match[1],
        confirmedNonce:
          nonces.get(match[1]) || 0,
        nextNonce: nextNonce(match[1])
      });
    }

    if (
      req.method === "POST" &&
      u.pathname === "/api/tx"
    ) {
      let body = "";
      try {
        for await (const part of req) {
          body += part;
          if (body.length > 12000) {
            throw Error("Request too large");
          }
        }
        const tx = JSON.parse(body);
        if (!verifyTx(tx)) {
          return json(res, 400, {
            error:
              "Invalid Ed25519 signature, record or ID"
          });
        }
        if (tx.nonce !== nextNonce(tx.from)) {
          return json(res, 409, {
            error: "Incorrect sender nonce"
          });
        }
        if (pending.length >= MAX_PENDING) {
          return json(res, 429, {
            error: "Queue full"
          });
        }
        pending.push(tx);
        return json(res, 202, {
          accepted: true,
          id: tx.id
        });
      } catch (e) {
        return json(res, 400, {
          error: e.message
        });
      }
    }

    json(res, 404, {
      error: "Not found"
    });
  });

  setInterval(() => {
    try {
      produce();
    } catch (e) {
      console.error(
        "Block production failed:", e.message
      );
    }
  }, 4000);

  server.listen(PORT, HOST, () => {
    console.log(
      `Privi developer explorer: http://${HOST}:${PORT}/` +
      `\nValidator: ${validator}` +
      `\nChain ID: ${CHAIN_ID}` +
      "\nNo real PRIV balances or BNB bridge."
    );
  });
}

(async () => {
  try {
    if (!(await cli())) {
      await start();
    }
  } catch (e) {
    console.error(e.message);
    process.exitCode = 1;
  }
})();

