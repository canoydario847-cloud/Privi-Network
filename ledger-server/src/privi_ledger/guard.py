"""Privi Guard: what blockchains need so AI agents can hold and move money safely.

Four parts, all tied to the organization's tamper-evident Ledger and Privi Passport:

1. Wallet policies   - per-wallet rules an agent cannot exceed: per-transaction and daily USD caps,
                       allowed chains and contracts, approval threshold, expiry, and the human
                       owner's wallet that must sign off on anything risky.
2. Transaction scan  - decodes calldata (transfers, approvals, NFT operator grants, permits,
                       admin calls), explains it in plain English, flags drainer patterns,
                       optionally simulates it over JSON-RPC, checks the counterparty with KYA,
                       and returns allow / needs_approval / block against the policy. Allowed
                       transactions get a Privi-signed Guard attestation.
3. Human approval    - a risky transaction waits for the owner's wallet signature (EIP-191).
   and escrow          The agent's API key alone can never approve its own transaction.
                       Agent-to-agent escrow between two Privi organizations, with release and
                       refund authorizations signed by the Privi Guard arbiter key (secp256k1),
                       verifiable on any EVM chain by ecrecover (see contracts/PriviEscrow.sol).
4. Agent registry    - public directory of agents: wallets, passport, endpoint, capabilities;
                       each record version is anchored on the Privi chain.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, decode_dss_signature

from .kya import _N, checksum, keccak256, norm_address, personal_hash, recover_address

GUARD_VERSION = "1"
APPROVAL_TTL_H = 24
ATTESTATION_TTL_MIN = 30
UNLIMITED = 2 ** 128          # allowances at or above this are treated as unlimited
ZERO = "0x" + "0" * 40

DEFAULT_RPCS = {
    8453: "https://mainnet.base.org",
    84532: "https://sepolia.base.org",
    262144: "https://privi-evm-devnet-development.up.railway.app",
}
CHAIN_NAMES = {1: "Ethereum", 8453: "Base", 84532: "Base Sepolia", 262144: "Privi EVM Devnet", 10: "Optimism",
               42161: "Arbitrum One", 137: "Polygon"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS guard_policies (
    org_id      TEXT NOT NULL,
    wallet      TEXT NOT NULL,             -- lowercase 0x
    policy      TEXT NOT NULL,             -- JSON
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (org_id, wallet)
);
CREATE TABLE IF NOT EXISTS guard_spend (
    org_id     TEXT NOT NULL,
    wallet     TEXT NOT NULL,
    usd        TEXT NOT NULL,
    tx_digest  TEXT NOT NULL,
    at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_guard_spend ON guard_spend (org_id, wallet, at);
CREATE TABLE IF NOT EXISTS guard_approvals (
    approval_id TEXT PRIMARY KEY,
    org_id      TEXT NOT NULL,
    wallet      TEXT NOT NULL,
    owner       TEXT NOT NULL,
    tx_digest   TEXT NOT NULL,
    request     TEXT NOT NULL,             -- JSON: tx, preview, reasons, usd
    status      TEXT NOT NULL,             -- pending | approved | rejected | used
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    decided_at  TEXT,
    decision_sig TEXT
);
CREATE TABLE IF NOT EXISTS guard_keys (
    key_id      TEXT PRIMARY KEY,
    private_hex TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guard_escrows (
    escrow_id   TEXT PRIMARY KEY,
    payer_org   TEXT NOT NULL,
    payee_org   TEXT NOT NULL,
    record      TEXT NOT NULL,             -- JSON terms
    status      TEXT NOT NULL,             -- offered | accepted | delivered | released | refunded | disputed | cancelled
    events      TEXT NOT NULL,             -- JSON list
    authorization TEXT,                    -- JSON arbiter authorization once released/refunded
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guard_registry (
    agent_id    TEXT PRIMARY KEY,
    org_id      TEXT NOT NULL,
    stream_id   TEXT NOT NULL,
    record      TEXT NOT NULL,             -- JSON, latest version
    record_hash TEXT NOT NULL,
    attestation TEXT NOT NULL,
    version     INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    revoked_at  TEXT,
    UNIQUE (org_id, stream_id)
);
CREATE TABLE IF NOT EXISTS guard_registry_versions (
    agent_id    TEXT NOT NULL,
    version     INTEGER NOT NULL,
    record_hash TEXT NOT NULL,
    attestation TEXT NOT NULL,
    at          TEXT NOT NULL,
    PRIMARY KEY (agent_id, version)
);
"""


class GuardError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def _usd(v: Any, what: str) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise ValueError(f"{what} must be a number")
    if d < 0:
        raise ValueError(f"{what} cannot be negative")
    return d


def _fmt(d: Decimal) -> str:
    return format(d.normalize(), "f")


def _hexbytes(data: str | None) -> bytes:
    s = (data or "").strip().lower().removeprefix("0x")
    if len(s) % 2 or any(c not in "0123456789abcdef" for c in s):
        raise ValueError("data must be 0x-prefixed hex")
    return bytes.fromhex(s)


def _int(v: Any, what: str) -> int:
    if isinstance(v, int):
        n = v
    else:
        s = str(v or "0").strip().lower()
        try:
            n = int(s, 16) if s.startswith("0x") else int(s)
        except ValueError:
            raise ValueError(f"{what} must be an integer (decimal or 0x hex)")
    if n < 0:
        raise ValueError(f"{what} cannot be negative")
    return n


# ---------------------------------------------------------------- calldata decoding

def selector(signature: str) -> str:
    return keccak256(signature.encode()).hex()[:8]


# signature -> (label, static argument types decoded from the head)
_KNOWN = {
    "transfer(address,uint256)": ("transfer", ["address", "uint256"]),
    "transferFrom(address,address,uint256)": ("transferFrom", ["address", "address", "uint256"]),
    "approve(address,uint256)": ("approve", ["address", "uint256"]),
    "increaseAllowance(address,uint256)": ("increaseAllowance", ["address", "uint256"]),
    "setApprovalForAll(address,bool)": ("setApprovalForAll", ["address", "bool"]),
    "permit(address,address,uint256,uint256,uint8,bytes32,bytes32)": ("permit", ["address", "address", "uint256", "uint256"]),
    "safeTransferFrom(address,address,uint256)": ("safeTransferFrom", ["address", "address", "uint256"]),
    "safeTransferFrom(address,address,uint256,bytes)": ("safeTransferFrom", ["address", "address", "uint256"]),
    "safeTransferFrom(address,address,uint256,uint256,bytes)": ("safeTransferFrom1155", ["address", "address", "uint256", "uint256"]),
    "transferOwnership(address)": ("transferOwnership", ["address"]),
    "renounceOwnership()": ("renounceOwnership", []),
    "upgradeTo(address)": ("upgradeTo", ["address"]),
    "upgradeToAndCall(address,bytes)": ("upgradeToAndCall", ["address"]),
    "deposit()": ("deposit", []),
    "withdraw(uint256)": ("withdraw", ["uint256"]),
    "multicall(bytes[])": ("multicall", []),
    "multicall(uint256,bytes[])": ("multicall", []),
    "execute(bytes,bytes[],uint256)": ("execute", []),
    "execute(bytes,bytes[])": ("execute", []),
    "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)": ("execTransaction", ["address", "uint256"]),
}
SELECTORS = {selector(sig): (label, types, sig) for sig, (label, types) in _KNOWN.items()}


def decode(data: bytes) -> dict[str, Any]:
    if not data:
        return {"function": None, "args": {}}
    if len(data) < 4:
        return {"function": "unknown", "selector": data.hex(), "args": {}}
    sel = data[:4].hex()
    hit = SELECTORS.get(sel)
    if not hit:
        return {"function": "unknown", "selector": "0x" + sel, "args": {}}
    label, types, sig = hit
    args: list[Any] = []
    body = data[4:]
    for i, t in enumerate(types):
        word = body[32 * i:32 * i + 32]
        if len(word) < 32:
            raise ValueError(f"calldata too short for {sig}")
        n = int.from_bytes(word, "big")
        args.append(checksum("0x" + word[-20:].hex()) if t == "address" else bool(n) if t == "bool" else n)
    return {"function": label, "signature": sig, "selector": "0x" + sel, "args": args}


def _amt(n: int) -> str:
    return "UNLIMITED" if n >= UNLIMITED else f"{n:,} (raw units)"


def explain(tx: dict, d: dict) -> tuple[str, list[dict], dict]:
    """Plain-English summary, risk findings and the parties the transaction touches."""
    risks: list[dict] = []
    to, frm, value = tx["to"], tx["from"], tx["value"]
    eth = Decimal(value) / Decimal(10 ** 18)
    parties: dict[str, str] = {"contract": to}
    fn, a = d.get("function"), d.get("args") or []

    def risk(sev: str, code: str, msg: str):
        risks.append({"severity": sev, "code": code, "message": msg})

    if fn is None:
        summary = f"Send {eth.normalize():f} native coin to {to}"
        parties = {"recipient": to}
        if to.lower() == ZERO:
            risk("critical", "burn_address", "Sending to the zero address destroys the funds.")
    elif fn in ("transfer",):
        summary = f"Transfer {_amt(a[1])} of token {to} to {a[0]}"
        parties["recipient"] = a[0]
        if a[0].lower() == ZERO:
            risk("critical", "burn_address", "Tokens sent to the zero address are destroyed.")
    elif fn == "transferFrom":
        summary = f"Move {_amt(a[2])} of token {to} from {a[0]} to {a[1]}"
        parties.update(source=a[0], recipient=a[1])
        if a[0].lower() != frm.lower():
            risk("medium", "moves_others_funds", f"Moves tokens out of {a[0]}, not out of the sending wallet.")
    elif fn in ("approve", "increaseAllowance"):
        summary = f"Allow {a[0]} to spend {_amt(a[1])} of token {to} from this wallet"
        parties["spender"] = a[0]
        if a[1] >= UNLIMITED:
            risk("high", "unlimited_approval", "Unlimited approval: the spender can take every token of this type, now or later.")
        elif a[1] == 0:
            summary = f"Revoke {a[0]}'s permission to spend token {to}"
    elif fn == "setApprovalForAll":
        parties["operator"] = a[0]
        if a[1]:
            summary = f"Give {a[0]} control of every NFT this wallet holds in collection {to}"
            risk("high", "nft_operator_grant", "Operator grant: this address could move every NFT in the collection. Common in NFT drainer scams.")
        else:
            summary = f"Remove {a[0]}'s control of NFTs in collection {to}"
    elif fn == "permit":
        summary = f"Signature-based approval: {a[1]} may spend {_amt(a[2])} of token {to} owned by {a[0]}"
        parties["spender"] = a[1]
        risk("high", "permit", "Permit approvals need no gas and are a common phishing route.")
        if a[2] >= UNLIMITED:
            risk("high", "unlimited_approval", "Unlimited permit approval.")
    elif fn in ("safeTransferFrom", "safeTransferFrom1155"):
        summary = f"Transfer NFT #{a[2]} of collection {to} from {a[0]} to {a[1]}"
        parties.update(source=a[0], recipient=a[1])
    elif fn in ("transferOwnership", "renounceOwnership", "upgradeTo", "upgradeToAndCall"):
        summary = {"transferOwnership": f"Hand ownership of contract {to} to {a[0] if a else ''}",
                   "renounceOwnership": f"Give up ownership of contract {to} forever",
                   "upgradeTo": f"Replace the code of contract {to} with {a[0] if a else ''}",
                   "upgradeToAndCall": f"Replace the code of contract {to} with {a[0] if a else ''} and run it"}[fn]
        risk("critical", "admin_action", "Administrative action on a contract. Agents should never do this without a human.")
    elif fn == "deposit":
        summary = f"Deposit {eth.normalize():f} native coin into {to}"
    elif fn == "withdraw":
        summary = f"Withdraw {a[0]:,} (raw units) from {to}"
    elif fn in ("multicall", "execute"):
        summary = f"Batched call ({d['signature']}) on {to}"
        risk("medium", "batched_call", "Batched transaction: the inner calls are not decoded, so Guard cannot explain them.")
    elif fn == "execTransaction":
        summary = f"Multisig (Safe) execution: call {a[0]} with {a[1]:,} wei"
        parties["target"] = a[0]
        risk("medium", "multisig_exec", "Executes a multisig transaction whose inner call is not decoded.")
    else:
        summary = f"Call unrecognized function {d.get('selector')} on {to}"
        risk("medium", "unknown_function", "Unrecognized function: Guard cannot say what this does.")
    if value and fn not in (None, "deposit"):
        summary += f", also sending {eth.normalize():f} native coin"
    return summary, risks, parties


# ---------------------------------------------------------------- JSON-RPC (optional simulation)

class Rpc:
    def __init__(self, urls: dict[int, str] | None = None, timeout: float = 8.0):
        self.urls, self.timeout = dict(DEFAULT_RPCS if urls is None else urls), timeout

    def _call(self, chain_id: int, method: str, params: list) -> Any:
        url = self.urls.get(chain_id)
        if not url:
            raise GuardError(f"no RPC configured for chain {chain_id}")
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                msg = json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise GuardError(f"RPC unavailable: {e}")
        if "error" in msg:
            raise GuardError(str(msg["error"].get("message", msg["error"])))
        return msg.get("result")

    def is_contract(self, chain_id: int, address: str) -> bool:
        code = self._call(chain_id, "eth_getCode", [address, "latest"]) or "0x"
        return len(code) > 2

    def simulate(self, chain_id: int, tx: dict) -> dict:
        try:
            out = self._call(chain_id, "eth_call", [{"from": tx["from"], "to": tx["to"], "value": hex(tx["value"]),
                                                     "data": tx["data"] or "0x"}, "latest"])
            return {"simulated": True, "reverts": False, "return_data": (out or "0x")[:202]}
        except GuardError as e:
            msg = str(e)
            if msg.startswith(("RPC unavailable", "no RPC")):
                return {"simulated": False, "reason": msg}
            return {"simulated": True, "reverts": True, "revert_reason": msg[:300]}


# ---------------------------------------------------------------- secp256k1 arbiter key

class Arbiter:
    """Privi Guard's EVM signing key. Signs escrow authorizations that a contract checks with ecrecover."""

    def __init__(self, db: sqlite3.Connection, lock: threading.Lock, private_hex: str = ""):
        if private_hex:
            n = int(private_hex.strip().removeprefix("0x"), 16)
        else:
            with lock:
                row = db.execute("SELECT private_hex FROM guard_keys WHERE key_id='arbiter'").fetchone()
                if row:
                    n = int(row["private_hex"], 16)
                else:
                    n = secrets.randbelow(_N - 1) + 1
                    db.execute("INSERT INTO guard_keys VALUES ('arbiter',?,?)", (f"{n:064x}", _iso(_now())))
                    db.commit()
        self._key = ec.derive_private_key(n, ec.SECP256K1())
        nums = self._key.public_key().public_numbers()
        pub = nums.x.to_bytes(32, "big") + nums.y.to_bytes(32, "big")
        self.address = checksum("0x" + keccak256(pub)[-20:].hex())

    def sign_digest(self, digest: bytes) -> str:
        """65-byte r||s||v signature over toEthSignedMessageHash(digest)."""
        h = keccak256(b"\x19Ethereum Signed Message:\n32" + digest)
        der = self._key.sign(h, ec.ECDSA(Prehashed(hashes.SHA256())))
        r, s = decode_dss_signature(der)
        if s > _N // 2:
            s = _N - s
        for v in (27, 28):
            sig = r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([v])
            if recover_address(h, sig).lower() == self.address.lower():
                return "0x" + sig.hex()
        raise GuardError("could not sign")


def escrow_digest(chain_id: int, contract: str, escrow_id: str, action: str, to: str, amount_atomic: int) -> bytes:
    """keccak256(abi.encodePacked("PriviEscrow", chainId, contract, id, action, to, amount)) as PriviEscrow.sol computes it."""
    eid = hashlib.sha256(escrow_id.encode()).digest()
    act = 1 if action == "release" else 2
    return keccak256(b"PriviEscrow" + chain_id.to_bytes(32, "big") + bytes.fromhex(norm_address(contract)[2:]) +
                     eid + bytes([act]) + bytes.fromhex(norm_address(to)[2:]) + amount_atomic.to_bytes(32, "big"))


# ---------------------------------------------------------------- the store

class Guard:
    def __init__(self, ledger, db: sqlite3.Connection, lock: threading.Lock, kya, passports, public_url: str,
                 rpc: Rpc | None = None, arbiter_key: str = "", escrow_contract: str = ""):
        self.ledger, self._db, self._lock, self.kya, self.passports = ledger, db, lock, kya, passports
        self.public_url, self.rpc = public_url, rpc
        self.escrow_contract = checksum(norm_address(escrow_contract)) if escrow_contract else None
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()
        self.arbiter = Arbiter(db, lock, arbiter_key)

    def _log(self, org_id: str, stream: str, action_type: str, summary: str, resource: str, outcome: str, details: dict):
        try:
            return self.ledger.record(org_id, stream, "Privi Guard", action_type, summary[:300], resource[:200], outcome, details)
        except ValueError:
            return None

    def _signed(self, body: dict) -> dict:
        h = sha(body)
        return {"body": body, "hash": h, "signature": self.passports.sign(h), "key_id": self.passports.key_id,
                "verify": "sha256(canonical JSON of body) == hash; Ed25519-verify signature with the issuer key at "
                          "/.well-known/privi-passport.json"}

    # ---------------- 1. wallet policies ----------------

    def set_policy(self, org_id: str, wallet: str, p: dict) -> dict:
        w = norm_address(wallet)
        b = self.kya.binding(w)
        if not b or b["org_id"] != org_id or b["revoked_at"]:
            raise GuardError("bind this wallet to your organization first (kya_challenge + kya_bind_wallet)")
        owner = norm_address(p.get("owner_address") or "")
        if owner == w:
            raise GuardError("owner_address must be the human's wallet, not the agent's own wallet")
        max_tx, cap = _usd(p.get("max_tx_usd"), "max_tx_usd"), _usd(p.get("daily_cap_usd"), "daily_cap_usd")
        if max_tx is None or cap is None:
            raise ValueError("max_tx_usd and daily_cap_usd are required")
        appr = _usd(p.get("approval_above_usd"), "approval_above_usd")
        chains = [int(c) for c in (p.get("allowed_chains") or [8453])]
        contracts = sorted({norm_address(c) for c in (p.get("allowed_contracts") or [])})
        exp = p.get("expires_at")
        if exp:
            try:
                exp = _iso(datetime.fromisoformat(str(exp).replace("Z", "+00:00")).astimezone(timezone.utc))
            except ValueError:
                raise ValueError("expires_at must be ISO 8601")
        policy = {"wallet": checksum(w), "stream_id": b["stream_id"], "owner_address": checksum(owner),
                  "max_tx_usd": _fmt(max_tx), "daily_cap_usd": _fmt(cap),
                  "approval_above_usd": _fmt(appr if appr is not None else min(max_tx, Decimal("100"))),
                  "allowed_chains": chains, "allowed_contracts": [checksum(c) for c in contracts],
                  "block_unlimited_approvals": bool(p.get("block_unlimited_approvals", True)),
                  "require_known_counterparty": bool(p.get("require_known_counterparty", False)),
                  "expires_at": exp, "active": bool(p.get("active", True))}
        with self._lock:
            self._db.execute("INSERT INTO guard_policies VALUES (?,?,?,?) ON CONFLICT (org_id, wallet) DO UPDATE SET "
                             "policy=excluded.policy, updated_at=excluded.updated_at", (org_id, w, canonical(policy), _iso(_now())))
            self._db.commit()
        e = self._log(org_id, "privi-guard", "data_change", f"Wallet policy set for {policy['wallet']}", policy["wallet"],
                      "success", {"policy_hash": sha(policy), **{k: policy[k] for k in ("max_tx_usd", "daily_cap_usd", "approval_above_usd")}})
        return {"policy": policy, "policy_hash": sha(policy), "recorded": bool(e)}

    def policy(self, org_id: str, wallet: str) -> dict | None:
        r = self._db.execute("SELECT policy FROM guard_policies WHERE org_id=? AND wallet=?", (org_id, norm_address(wallet))).fetchone()
        return json.loads(r["policy"]) if r else None

    def policies(self, org_id: str) -> list[dict]:
        rows = self._db.execute("SELECT policy FROM guard_policies WHERE org_id=? ORDER BY updated_at DESC", (org_id,)).fetchall()
        return [json.loads(r["policy"]) for r in rows]

    def spent_24h(self, org_id: str, wallet: str) -> Decimal:
        since = _iso(_now() - timedelta(hours=24))
        rows = self._db.execute("SELECT usd FROM guard_spend WHERE org_id=? AND wallet=? AND at>?",
                                (org_id, norm_address(wallet), since)).fetchall()
        return sum((Decimal(r["usd"]) for r in rows), Decimal("0"))

    # ---------------- 2. transaction scan ----------------

    def normalize_tx(self, tx: dict) -> dict:
        data = _hexbytes(tx.get("data"))
        return {"chain_id": _int(tx.get("chain_id", 8453), "chain_id"), "from": checksum(norm_address(tx.get("from", ""))),
                "to": checksum(norm_address(tx.get("to", ""))), "value": _int(tx.get("value", 0), "value"),
                "data": "0x" + data.hex()}

    def preview(self, tx: dict, simulate: bool = True) -> dict:
        t = self.normalize_tx(tx)
        d = decode(_hexbytes(t["data"]))
        summary, risks, parties = explain(t, d)
        out: dict[str, Any] = {"tx": t, "tx_digest": sha(t), "chain": CHAIN_NAMES.get(t["chain_id"], f"chain {t['chain_id']}"),
                               "decoded": d, "summary": summary, "parties": parties}
        checks: dict[str, Any] = {}
        for role, addr in parties.items():
            if role == "contract" and d.get("function") is not None:
                continue
            try:
                k = self.kya.check(addr, 550, None, True)
                checks[role] = {"address": k["address"], "known_agent": k["known"], "kya_allow": k["allow"],
                                "organization": k.get("organization"), "score": k.get("current_score")}
                if k["known"] and not k["allow"]:
                    risks.append({"severity": "medium", "code": "counterparty_low_trust",
                                  "message": f"{role} {k['address']} is an agent wallet that fails KYA: {'; '.join(k['reasons'][:2])}"})
            except ValueError:
                pass
        out["counterparties"] = checks
        if self.rpc and simulate:
            sim = self.rpc.simulate(t["chain_id"], t)
            out["simulation"] = sim
            if sim.get("reverts"):
                risks.append({"severity": "high", "code": "would_revert", "message": f"Simulation says this transaction fails: {sim.get('revert_reason')}"})
            spender = parties.get("spender") or parties.get("operator")
            if spender and d.get("function") in ("approve", "increaseAllowance", "setApprovalForAll", "permit"):
                try:
                    if not self.rpc.is_contract(t["chain_id"], spender):
                        risks.append({"severity": "high", "code": "approval_to_personal_wallet",
                                      "message": f"{spender} is a personal wallet, not a contract. Approving a personal wallet is the classic drainer pattern."})
                except GuardError:
                    pass
        else:
            out["simulation"] = {"simulated": False, "reason": "simulation not requested or no RPC configured"}
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        out["risks"] = sorted(risks, key=lambda r: order.get(r["severity"], 9))
        out["risk_level"] = out["risks"][0]["severity"] if out["risks"] else "low"
        return out

    def check(self, org_id: str, tx: dict, usd_value: Any, approval_id: str | None, simulate: bool, purpose: str) -> dict:
        pv = self.preview(tx, simulate)
        t, wallet = pv["tx"], pv["tx"]["from"]
        p = self.policy(org_id, wallet)
        block, ask = [], []
        usd = _usd(usd_value, "usd_value")
        moves_value = t["value"] > 0 or pv["decoded"].get("function") in (
            "transfer", "transferFrom", "approve", "increaseAllowance", "permit", "safeTransferFrom", "safeTransferFrom1155", "setApprovalForAll")
        if not p:
            block.append("no Guard policy for this wallet: set one with guard_policy_set")
        else:
            if not p["active"]:
                block.append("policy is paused")
            if p["expires_at"] and p["expires_at"] < _iso(_now()):
                block.append("policy expired")
            if t["chain_id"] not in p["allowed_chains"]:
                block.append(f"chain {t['chain_id']} is not allowed by policy")
            if p["allowed_contracts"] and t["to"].lower() not in [c.lower() for c in p["allowed_contracts"]]:
                block.append(f"{t['to']} is not on the allowed contracts list")
            if p["block_unlimited_approvals"] and any(r["code"] == "unlimited_approval" for r in pv["risks"]):
                block.append("policy blocks unlimited approvals")
            if any(r["severity"] == "critical" for r in pv["risks"]):
                block.append("critical risk: " + next(r["message"] for r in pv["risks"] if r["severity"] == "critical"))
            if usd is not None:
                if usd > Decimal(p["max_tx_usd"]):
                    block.append(f"${_fmt(usd)} is over the per-transaction limit of ${p['max_tx_usd']}")
                spent = self.spent_24h(org_id, wallet)
                if spent + usd > Decimal(p["daily_cap_usd"]):
                    block.append(f"${_fmt(usd)} would bring 24-hour spend to ${_fmt(spent + usd)}, over the daily cap of ${p['daily_cap_usd']}")
                if usd > Decimal(p["approval_above_usd"]):
                    ask.append(f"${_fmt(usd)} is over the ${p['approval_above_usd']} approval threshold")
            elif moves_value:
                ask.append("usd_value was not given for a transaction that moves or exposes funds")
            if p["require_known_counterparty"]:
                cp = pv["counterparties"].get("recipient") or pv["counterparties"].get("spender")
                if not cp or not cp["kya_allow"]:
                    ask.append("counterparty is not a KYA-verified agent")
            for r in pv["risks"]:
                if r["severity"] == "high":
                    ask.append(r["message"])
        approval = None
        if approval_id and not block:
            approval = self._approval(approval_id)
            if not approval or approval["org_id"] != org_id:
                block.append("no such approval for this organization")
            elif approval["tx_digest"] != pv["tx_digest"]:
                block.append("approval was for a different transaction")
            elif approval["status"] != "approved":
                block.append(f"approval is {approval['status']}")
            elif approval["expires_at"] < _iso(_now()):
                block.append("approval expired")
            else:
                ask = []
        verdict = "block" if block else "needs_approval" if ask else "allow"
        out = {"verdict": verdict, "reasons": block or ask, **pv, "policy": p,
               "usd_value": _fmt(usd) if usd is not None else None}
        stream = (p or {}).get("stream_id") or "privi-guard"
        stream = "privi-guard" if stream == "*" else stream
        if verdict == "needs_approval" and p:
            out["approval"] = self._request_approval(org_id, wallet, p["owner_address"], pv, ask, usd)
        if verdict == "allow":
            with self._lock:
                self._db.execute("INSERT INTO guard_spend VALUES (?,?,?,?,?)",
                                 (org_id, norm_address(wallet), _fmt(usd or Decimal(0)), pv["tx_digest"], _iso(_now())))
                if approval:
                    self._db.execute("UPDATE guard_approvals SET status='used' WHERE approval_id=?", (approval_id,))
                self._db.commit()
            out["guard_attestation"] = self._signed({
                "type": "PriviGuard", "version": GUARD_VERSION, "verdict": "allow", "tx_digest": pv["tx_digest"],
                "chain_id": t["chain_id"], "from": t["from"], "to": t["to"], "usd_value": out["usd_value"],
                "approval_id": approval_id if approval else None, "org_id": org_id,
                "issued_at": _iso(_now()), "expires_at": _iso(_now() + timedelta(minutes=ATTESTATION_TTL_MIN))})
        e = self._log(org_id, stream, "payment" if moves_value else "decision",
                      f"Guard {verdict}: {pv['summary']}" + (f" ({purpose[:80]})" if purpose else ""), pv["tx_digest"],
                      {"allow": "success", "block": "blocked", "needs_approval": "pending"}[verdict],
                      {"reasons": (block or ask)[:6], "usd_value": out["usd_value"], "risk_level": pv["risk_level"]})
        if e:
            out["recorded_in_your_log"] = {"stream_id": stream, "entry_hash": e["entry_hash"]}
        return out

    # ---------------- 3a. human approval ----------------

    @staticmethod
    def approval_message(approval_id: str, wallet: str, digest: str, decision: str) -> str:
        return (f"Privi Guard approval\nApproval: {approval_id}\nAgent wallet: {wallet}\nTransaction digest: {digest}\n"
                f"Decision: {decision}")

    def _request_approval(self, org_id: str, wallet: str, owner: str, pv: dict, reasons: list[str], usd) -> dict:
        row = self._db.execute("SELECT approval_id FROM guard_approvals WHERE org_id=? AND tx_digest=? AND status='pending' "
                               "AND expires_at>?", (org_id, pv["tx_digest"], _iso(_now()))).fetchone()
        aid = row["approval_id"] if row else "apr_" + secrets.token_hex(8)
        if not row:
            req = {"tx": pv["tx"], "summary": pv["summary"], "risks": pv["risks"], "reasons": reasons,
                   "usd_value": _fmt(usd) if usd is not None else None, "chain": pv["chain"]}
            with self._lock:
                self._db.execute("INSERT INTO guard_approvals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                 (aid, org_id, norm_address(wallet), norm_address(owner), pv["tx_digest"], canonical(req),
                                  "pending", _iso(_now()), _iso(_now() + timedelta(hours=APPROVAL_TTL_H)), None, None))
                self._db.commit()
        return {"approval_id": aid, "owner_address": owner, "status": "pending",
                "approve_url": f"{self.public_url}/guard/approvals/{aid}",
                "message_to_sign": self.approval_message(aid, wallet, pv["tx_digest"], "approve"),
                "next": "The owner opens approve_url (or signs message_to_sign with their wallet and calls guard_approve). "
                        "Then call guard_check_tx again with the same transaction and this approval_id."}

    def _approval(self, approval_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM guard_approvals WHERE approval_id=?", (approval_id,)).fetchone()
        if not r:
            return None
        return {k: r[k] for k in r.keys()} | {"request": json.loads(r["request"])}

    def approval_public(self, approval_id: str) -> dict | None:
        a = self._approval(approval_id)
        if not a:
            return None
        status = "expired" if a["status"] == "pending" and a["expires_at"] < _iso(_now()) else a["status"]
        w = checksum(a["wallet"])
        return {"approval_id": approval_id, "status": status, "agent_wallet": w, "owner_address": checksum(a["owner"]),
                "tx_digest": a["tx_digest"], "request": a["request"], "created_at": a["created_at"],
                "expires_at": a["expires_at"], "decided_at": a["decided_at"],
                "messages": {d: self.approval_message(approval_id, w, a["tx_digest"], d) for d in ("approve", "reject")}}

    def decide(self, approval_id: str, decision: str, signature: str) -> dict:
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject")
        a = self._approval(approval_id)
        if not a:
            raise GuardError("no such approval")
        if a["status"] != "pending":
            raise GuardError(f"approval is already {a['status']}")
        if a["expires_at"] < _iso(_now()):
            raise GuardError("approval expired; the agent must request a new one")
        msg = self.approval_message(approval_id, checksum(a["wallet"]), a["tx_digest"], decision)
        try:
            signer = recover_address(personal_hash(msg), _hexbytes(signature))
        except ValueError as e:
            raise GuardError(f"bad signature: {e}")
        if signer.lower() != a["owner"]:
            raise GuardError("signature is not from the policy owner's wallet")
        status = "approved" if decision == "approve" else "rejected"
        with self._lock:
            self._db.execute("UPDATE guard_approvals SET status=?, decided_at=?, decision_sig=? WHERE approval_id=?",
                             (status, _iso(_now()), signature, approval_id))
            self._db.commit()
        self._log(a["org_id"], "privi-guard", "approval", f"Owner {status} transaction {a['tx_digest'][:16]}: "
                  f"{a['request']['summary']}", approval_id, "success" if status == "approved" else "blocked",
                  {"owner": checksum(a["owner"]), "tx_digest": a["tx_digest"]})
        return {"approval_id": approval_id, "status": status, "signed_by": checksum(signer)}

    def approvals(self, org_id: str, status: str | None) -> list[dict]:
        q = "SELECT approval_id FROM guard_approvals WHERE org_id=?" + (" AND status=?" if status else "") + " ORDER BY created_at DESC LIMIT 100"
        rows = self._db.execute(q, (org_id, status) if status else (org_id,)).fetchall()
        return [self.approval_public(r["approval_id"]) for r in rows]

    # ---------------- 3b. agent-to-agent escrow ----------------

    def _escrow(self, escrow_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM guard_escrows WHERE escrow_id=?", (escrow_id,)).fetchone()
        if not r:
            return None
        return {"escrow_id": r["escrow_id"], "payer_org": r["payer_org"], "payee_org": r["payee_org"],
                "terms": json.loads(r["record"]), "status": r["status"], "events": json.loads(r["events"]),
                "authorization": json.loads(r["authorization"]) if r["authorization"] else None,
                "created_at": r["created_at"], "updated_at": r["updated_at"]}

    def _escrow_update(self, e: dict, status: str, event: dict, auth: dict | None = None):
        e["events"].append({**event, "at": _iso(_now()), "status": status})
        with self._lock:
            self._db.execute("UPDATE guard_escrows SET status=?, events=?, authorization=COALESCE(?, authorization), updated_at=? "
                             "WHERE escrow_id=?", (status, canonical(e["events"]), canonical(auth) if auth else None,
                                                   _iso(_now()), e["escrow_id"]))
            self._db.commit()
        e["status"] = status
        if auth:
            e["authorization"] = auth

    def escrow_open(self, payer_org: str, payee_org: str, amount: str, payer_wallet: str, payee_wallet: str, chain_id: int,
                    token: str, decimals: int, terms: str, deadline_hours: float) -> dict:
        if payer_org == payee_org:
            raise GuardError("payer and payee must be different organizations")
        if not self.ledger.org_exists(payee_org):
            raise GuardError("payee organization is not on Privi Ledger")
        amt = _usd(amount, "amount")
        if not amt or amt <= 0:
            raise ValueError("amount must be positive")
        if not (0 <= int(decimals) <= 36):
            raise ValueError("decimals must be 0-36")
        if not (0 < float(deadline_hours) <= 24 * 90):
            raise ValueError("deadline_hours must be between 0 and 2160")
        atomic = int((amt * (Decimal(10) ** int(decimals))).to_integral_value())
        pw = norm_address(payer_wallet)
        b = self.kya.binding(pw)
        if not b or b["org_id"] != payer_org or b["revoked_at"]:
            raise GuardError("payer_wallet must be bound to your organization (kya_bind_wallet)")
        eid = "esc_" + secrets.token_hex(8)
        rec = {"escrow_id": eid, "payer_org": payer_org, "payee_org": payee_org, "payer_wallet": checksum(pw),
               "payee_wallet": checksum(norm_address(payee_wallet)), "chain_id": int(chain_id),
               "token": checksum(norm_address(token)), "decimals": int(decimals), "amount": _fmt(amt), "amount_atomic": str(atomic),
               "terms": terms.strip()[:4000], "deadline": _iso(_now() + timedelta(hours=float(deadline_hours))),
               "escrow_contract": self.escrow_contract, "arbiter": self.arbiter.address}
        rec["terms_hash"] = sha({k: v for k, v in rec.items() if k != "escrow_contract"})
        ev = [{"by": payer_org, "event": "offered", "at": _iso(_now()), "status": "offered"}]
        with self._lock:
            self._db.execute("INSERT INTO guard_escrows VALUES (?,?,?,?,?,?,?,?,?)",
                             (eid, payer_org, payee_org, canonical(rec), "offered", canonical(ev), None, _iso(_now()), _iso(_now())))
            self._db.commit()
        self._log(payer_org, "privi-escrow", "payment", f"Escrow {eid} offered to {payee_org}: {amt} of {rec['token']}",
                  eid, "pending", {"terms_hash": rec["terms_hash"]})
        self._log(payee_org, "privi-escrow", "payment", f"Escrow {eid} offered by {payer_org}: {amt} of {rec['token']}",
                  eid, "pending", {"terms_hash": rec["terms_hash"]})
        return {**self._escrow(eid), "next": "Payee calls guard_escrow_act with action 'accept'. Payer then funds the escrow "
                "contract (if deployed) or holds funds until release."}

    def escrow_act(self, org_id: str, escrow_id: str, action: str, note: str = "", tx_hash: str = "") -> dict:
        e = self._escrow(escrow_id)
        if not e or org_id not in (e["payer_org"], e["payee_org"]):
            raise GuardError("no such escrow for your organization")
        role = "payer" if org_id == e["payer_org"] else "payee"
        st, t = e["status"], e["terms"]
        past_deadline = t["deadline"] < _iso(_now())
        allowed = {
            ("payee", "accept"): {"offered"},
            ("payer", "cancel"): {"offered"},
            ("payee", "deliver"): {"accepted"},
            ("payer", "fund"): {"accepted", "delivered"},
            ("payer", "release"): {"accepted", "delivered", "disputed"},
            ("payee", "refund"): {"accepted", "delivered", "disputed"},
            ("payer", "refund"): {"accepted", "disputed"},
            ("payer", "dispute"): {"accepted", "delivered"},
            ("payee", "dispute"): {"accepted", "delivered"},
        }.get((role, action))
        if allowed is None:
            raise GuardError(f"the {role} cannot '{action}' an escrow")
        if st not in allowed:
            raise GuardError(f"cannot {action} an escrow that is {st}")
        if role == "payer" and action == "refund" and not (past_deadline or st == "disputed"):
            raise GuardError("the payer can claim a refund only after the deadline passes without delivery, or in a dispute")
        if role == "payer" and action == "refund" and st == "disputed" and not past_deadline:
            raise GuardError("a disputed escrow can be refunded by the payer only after the deadline; or the payee can refund")
        event = {"by": org_id, "role": role, "event": action, "note": note[:500]}
        if tx_hash:
            event["tx_hash"] = tx_hash[:80]
        new = {"accept": "accepted", "cancel": "cancelled", "deliver": "delivered", "fund": st, "release": "released",
               "refund": "refunded", "dispute": "disputed"}[action]
        auth = None
        if action in ("release", "refund"):
            to = t["payee_wallet"] if action == "release" else t["payer_wallet"]
            contract = t.get("escrow_contract") or ZERO
            dg = escrow_digest(t["chain_id"], contract, escrow_id, action, to, int(t["amount_atomic"]))
            auth = {"action": action, "escrow_id": escrow_id, "escrow_id_bytes32": "0x" + hashlib.sha256(escrow_id.encode()).hexdigest(),
                    "chain_id": t["chain_id"], "escrow_contract": contract, "to": to, "token": t["token"],
                    "amount_atomic": t["amount_atomic"], "digest": "0x" + dg.hex(),
                    "arbiter": self.arbiter.address, "arbiter_signature": self.arbiter.sign_digest(dg),
                    "verify": "ecrecover(toEthSignedMessageHash(digest), arbiter_signature) == arbiter; "
                              "digest = keccak256(abi.encodePacked('PriviEscrow', chainId, contract, id, action(1=release,2=refund), to, amount))"}
        self._escrow_update(e, new, event, auth)
        for o in (e["payer_org"], e["payee_org"]):
            self._log(o, "privi-escrow", "payment" if action in ("fund", "release", "refund") else "decision",
                      f"Escrow {escrow_id} {action} by {role}", escrow_id,
                      "blocked" if action in ("cancel", "dispute") else "success", {"status": new, "terms_hash": t["terms_hash"]})
        return self._escrow(escrow_id)

    def escrow_list(self, org_id: str) -> list[dict]:
        rows = self._db.execute("SELECT escrow_id FROM guard_escrows WHERE payer_org=? OR payee_org=? ORDER BY created_at DESC LIMIT 100",
                                (org_id, org_id)).fetchall()
        return [self._escrow(r["escrow_id"]) for r in rows]

    def escrow_public(self, escrow_id: str) -> dict | None:
        e = self._escrow(escrow_id)
        if not e:
            return None
        t = e["terms"]
        return {"escrow_id": escrow_id, "status": e["status"], "payer_org": e["payer_org"], "payee_org": e["payee_org"],
                "chain_id": t["chain_id"], "token": t["token"], "amount": t["amount"], "deadline": t["deadline"],
                "terms_hash": t["terms_hash"], "arbiter": t["arbiter"], "events": [{k: v for k, v in x.items() if k != "note"} for x in e["events"]],
                "authorization": e["authorization"]}

    # ---------------- 4. agent registry ----------------

    def registry_build(self, org: dict, stream_id: str, name: str, description: str, endpoint: str,
                       capabilities: list[str]) -> dict:
        wallets = [w["address"] for w in self.kya.list_for(org["org_id"])
                   if w and not w["revoked_at"] and w["stream_id"] in (stream_id, "*")]
        pp = self._db.execute("SELECT passport_id, score, grade FROM passports WHERE org_id=? AND stream_id IN (?, '*') AND "
                              "revoked_at IS NULL AND expires_at>? ORDER BY created_at DESC LIMIT 1",
                              (org["org_id"], stream_id, _iso(_now()))).fetchone()
        row = self._db.execute("SELECT agent_id, version, created_at FROM guard_registry WHERE org_id=? AND stream_id=?",
                               (org["org_id"], stream_id)).fetchone()
        aid = row["agent_id"] if row else "agt_" + secrets.token_hex(8)
        return {"type": "PriviAgentRecord", "version": GUARD_VERSION, "agent_id": aid, "record_version": (row["version"] + 1) if row else 1,
                "org_id": org["org_id"], "organization": org["name"], "stream_id": stream_id,
                "name": name.strip()[:120] or stream_id, "description": description.strip()[:1000],
                "endpoint": endpoint.strip()[:500] or None, "capabilities": sorted({c.strip()[:60] for c in capabilities if c.strip()})[:30],
                "wallets": wallets, "passport_id": pp["passport_id"] if pp else None,
                "passport_grade": pp["grade"] if pp else None, "updated_at": _iso(_now())}

    def registry_save(self, rec: dict, h: str, att: dict) -> None:
        with self._lock:
            exists = self._db.execute("SELECT 1 FROM guard_registry WHERE agent_id=?", (rec["agent_id"],)).fetchone()
            if exists:
                self._db.execute("UPDATE guard_registry SET record=?, record_hash=?, attestation=?, version=?, updated_at=?, "
                                 "revoked_at=NULL WHERE agent_id=?", (canonical(rec), h, canonical(att), rec["record_version"],
                                                                      _iso(_now()), rec["agent_id"]))
            else:
                self._db.execute("INSERT INTO guard_registry VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (rec["agent_id"], rec["org_id"], rec["stream_id"], canonical(rec), h, canonical(att),
                                  rec["record_version"], _iso(_now()), _iso(_now()), None))
            self._db.execute("INSERT INTO guard_registry_versions VALUES (?,?,?,?,?)",
                             (rec["agent_id"], rec["record_version"], h, canonical(att), _iso(_now())))
            self._db.commit()
        self._log(rec["org_id"], "privi-registry", "data_change", f"Agent {rec['name']} registered (v{rec['record_version']})",
                  rec["agent_id"], "success", {"record_hash": h, "anchored": att.get("anchored")})

    def _reg_row(self, r) -> dict:
        return {"agent": json.loads(r["record"]), "record_hash": r["record_hash"], "attestation": json.loads(r["attestation"]),
                "revoked": bool(r["revoked_at"]), "revoked_at": r["revoked_at"],
                "public_url": f"{self.public_url}/registry/{r['agent_id']}"}

    def registry_get(self, agent_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM guard_registry WHERE agent_id=?", (agent_id,)).fetchone()
        return self._reg_row(r) if r else None

    def registry_search(self, query: str = "", address: str = "", capability: str = "", limit: int = 25) -> list[dict]:
        rows = self._db.execute("SELECT * FROM guard_registry WHERE revoked_at IS NULL ORDER BY updated_at DESC LIMIT 1000").fetchall()
        out, q, cap = [], query.strip().lower(), capability.strip().lower()
        addr = norm_address(address) if address else ""
        for r in rows:
            rec = json.loads(r["record"])
            if addr and addr not in [w.lower() for w in rec["wallets"]]:
                continue
            if cap and cap not in [c.lower() for c in rec["capabilities"]]:
                continue
            if q and q not in " ".join([rec["name"], rec["description"], rec["organization"], rec["agent_id"]]).lower():
                continue
            out.append(self._reg_row(r))
            if len(out) >= limit:
                break
        return out

    def registry_revoke(self, org_id: str, agent_id: str) -> dict:
        with self._lock:
            r = self._db.execute("SELECT org_id FROM guard_registry WHERE agent_id=?", (agent_id,)).fetchone()
            if not r or r["org_id"] != org_id:
                raise GuardError("no such agent in your organization")
            self._db.execute("UPDATE guard_registry SET revoked_at=? WHERE agent_id=?", (_iso(_now()), agent_id))
            self._db.commit()
        self._log(org_id, "privi-registry", "data_change", f"Agent {agent_id} removed from registry", agent_id, "success", {})
        return {"agent_id": agent_id, "revoked": True}

    def registry_count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM guard_registry WHERE revoked_at IS NULL").fetchone()[0]


APPROVAL_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privi Guard approval</title><style>
:root{--bg:#f3f5f9;--fg:#141b2b;--mu:#5b6578;--line:#d5dbe6;--card:#fff;--ac:#2747d6;--bad:#b4252f;--warn:#a2610a}
@media (prefers-color-scheme:dark){:root{--bg:#0d1220;--fg:#e7ebf4;--mu:#97a1b6;--line:#2a3349;--card:#161d2e;--ac:#7d95ff;--bad:#ff8088;--warn:#f0b35a}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;padding:24px 16px}
main{max-width:640px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
.c{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
h1{font-size:24px;margin:0} .mu{color:var(--mu);font-size:13px} code,pre{font:12px/1.5 ui-monospace,monospace;white-space:pre-wrap;word-break:break-all}
.r{padding:8px 10px;border-radius:8px;border:1px solid var(--line);margin-top:6px} .critical,.high{border-color:var(--bad)} .medium{border-color:var(--warn)}
button{font:600 15px system-ui;padding:11px 18px;border-radius:10px;border:1px solid var(--ac);background:var(--ac);color:#fff;cursor:pointer}
button.no{background:transparent;color:var(--bad);border-color:var(--bad)} #out{font-size:14px}
</style></head><body><main>
<h1>Approve an AI agent transaction?</h1>
<div class="c" id="info">Loading…</div>
<div class="c"><div class="mu">Sign with the owner wallet shown above (MetaMask, Coinbase Wallet or any EIP-1193 wallet).</div>
<p style="display:flex;gap:10px;flex-wrap:wrap"><button id="yes">Approve</button><button class="no" id="no">Reject</button></p><div id="out"></div></div>
<p class="mu">Privi Guard by Privi World Co. Nothing is sent on-chain by signing; your signature only tells Guard your decision.</p>
</main><script>
const id=location.pathname.split("/").pop();let A=null;const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
fetch("/guard/approvals/"+id+".json").then(r=>r.json()).then(a=>{A=a;if(a.error){$("#info").textContent=a.error;return}
const q=a.request;$("#info").innerHTML=`<div class="mu">Status: <b>${esc(a.status)}</b> · expires ${esc(a.expires_at)}</div>
<p><b>${esc(q.summary)}</b></p><div class="mu">${esc(q.chain)} · value $${esc(q.usd_value??"not stated")}</div>
<p class="mu">Agent wallet <code>${esc(a.agent_wallet)}</code><br>Owner wallet <code>${esc(a.owner_address)}</code></p>
${(q.risks||[]).map(r=>`<div class="r ${esc(r.severity)}"><b>${esc(r.severity)}</b> ${esc(r.message)}</div>`).join("")}
${(q.reasons||[]).length?`<p class="mu">Why it needs you: ${esc(q.reasons.join("; "))}</p>`:""}`;
if(a.status!=="pending"){$("#yes").disabled=$("#no").disabled=true}}).catch(()=>{$("#info").textContent="Could not load this approval."});
async function decide(d){const out=$("#out");try{if(!window.ethereum){out.textContent="No browser wallet found. Sign this message with the owner wallet and call guard_approve:\\n\\n"+A.messages[d];return}
const [acct]=await window.ethereum.request({method:"eth_requestAccounts"});
const msg=A.messages[d];const hex="0x"+Array.from(new TextEncoder().encode(msg)).map(b=>b.toString(16).padStart(2,"0")).join("");
const sig=await window.ethereum.request({method:"personal_sign",params:[hex,acct]});
const r=await fetch("/guard/approvals/"+id+"/decide",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({decision:d,signature:sig})});
const j=await r.json();out.textContent=j.error?("Not accepted: "+j.error):("Done: "+j.status+". The agent can continue.");if(!j.error){$("#yes").disabled=$("#no").disabled=true}}
catch(e){out.textContent="Signing was cancelled or failed: "+(e.message||e)}}
$("#yes").onclick=()=>decide("approve");$("#no").onclick=()=>decide("reject");
</script></body></html>"""
