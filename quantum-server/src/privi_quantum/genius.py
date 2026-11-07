# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi GENIUS: reserve-report evidence for stablecoin issuers and a stablecoin check for everyone who accepts them.

The GENIUS Act (signed 18 July 2025; in force 18 January 2027 per the OCC final rule, Bulletin 2026-50) requires a
permitted payment stablecoin issuer to hold reserves of at least 1:1 in a short list of liquid assets, to publish a
reserve composition report every month, to have that report examined by a registered public accounting firm, and to
have the CEO and CFO certify it. From 18 July 2028, digital asset service providers may not offer U.S. persons a
payment stablecoin unless a permitted (or qualifying foreign) issuer stands behind it.

What Privi does
  For issuers: takes each monthly report, runs the mechanical checks the statute spells out (1:1 coverage, permitted
  asset classes, Treasury maturity of 93 days or less, overnight repos, posting deadline, on-chain supply match),
  collects CEO and CFO certifications as passkey signatures (user verified on their own devices), records the
  accounting firm's examination (letter SHA-256 and optionally the examiner's passkey), and seals the result as an
  Ed25519 + ML-DSA-87 signed record with a public verification page.
  For agents, wallets, exchanges, merchants and x402 sellers: one call answers "who issues this stablecoin, what
  licensing status has been recorded, and is its latest reserve report sealed, current, examined and 1:1?"

What Privi does not do
  It does not grant, verify or replace a license, an examination or a regulator's judgement. License statuses are
  recorded by the operator with the regulator's source document; check results are evidence, not legal opinions.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from .humans import HumanError, HumanRegistry, b64u, unb64u

EFFECTIVE_DATE = "2027-01-18"
DASP_DEADLINE = "2028-07-18"
PLAN = {"plan": "Privi GENIUS Reserve Seal", "usd_per_month": 499, "pay": "https://privi-hub.onrender.com/pay/#genius"}
LICENSE_STATUSES = ("permitted", "applied", "foreign_comparable", "not_permitted", "unknown")
ROLES = ("CEO", "CFO", "EXAMINER")
ENROLL_TTL_S = 7 * 86400
SUPPLY_TOLERANCE = 0.005          # 0.5% between reported and on-chain supply (timing differences)
STALE_DAYS = 62                   # a report older than this is not "current"

# GENIUS Act s.4(a)(1)(A) reserve assets, as summarized; "max_days" is the longest remaining maturity allowed.
ASSET_CLASSES: dict[str, dict[str, Any]] = {
    "us_currency": {"label": "U.S. coins and currency (or Federal Reserve balances)", "max_days": None},
    "demand_deposits": {"label": "Demand deposits / insured shares at insured depository institutions", "max_days": None},
    "treasury_bills": {"label": "Treasury bills, notes or bonds with remaining maturity of 93 days or less", "max_days": 93},
    "treasury_repo": {"label": "Overnight repurchase agreements backed by Treasuries of 93 days or less", "max_days": 1},
    "treasury_reverse_repo": {"label": "Overnight reverse repurchase agreements collateralized by Treasuries", "max_days": 1},
    "government_mmf": {"label": "Money market fund shares invested solely in the assets above", "max_days": None},
    "regulator_approved": {"label": "Other similarly liquid federal government asset approved by the regulator", "max_days": None},
    "tokenized_eligible": {"label": "Tokenized form of an asset above (in compliance with applicable law)", "max_days": 93},
}

RPC = {"base": "https://mainnet.base.org", "ethereum": "https://ethereum-rpc.publicnode.com",
       "arbitrum": "https://arb1.arbitrum.io/rpc", "optimism": "https://mainnet.optimism.io",
       "polygon": "https://polygon-rpc.com"}
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS gen_issuers (
    issuer_id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, paid_until TEXT NOT NULL,
    license_status TEXT NOT NULL DEFAULT 'unknown', regulator TEXT NOT NULL DEFAULT '', license_source TEXT NOT NULL DEFAULT '',
    license_updated_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gen_coins (
    chain TEXT NOT NULL, address TEXT NOT NULL, issuer_id TEXT NOT NULL, symbol TEXT NOT NULL, decimals INTEGER NOT NULL,
    PRIMARY KEY (chain, address)
);
CREATE TABLE IF NOT EXISTS gen_officers (
    officer_id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
    enroll_hash TEXT, enroll_until REAL, enroll_nonce TEXT, human_id TEXT, enrolled_at TEXT, removed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS gen_reports (
    report_id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL, period TEXT NOT NULL, body TEXT NOT NULL, checks TEXT NOT NULL,
    nonce TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, sealed_at TEXT, receipt_id TEXT,
    UNIQUE (issuer_id, period)
);
CREATE TABLE IF NOT EXISTS gen_signoffs (
    report_id TEXT NOT NULL, officer_id TEXT NOT NULL, role TEXT NOT NULL, signed_at TEXT NOT NULL, credential_sha256 TEXT NOT NULL,
    PRIMARY KEY (report_id, officer_id)
);
"""


class GeniusError(ValueError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime | None = None) -> str:
    return (d or _now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _money(v: Any, what: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise GeniusError(f"{what} must be a number (U.S. dollars)")
    if f < 0 or f != f or f > 1e15:
        raise GeniusError(f"{what} is out of range")
    return round(f, 2)


def posting_deadline(period: str) -> date:
    """Report for month YYYY-MM is due by the last day of the following month."""
    y, m = (int(x) for x in period.split("-"))
    ny, nm = (y + (m == 12), m % 12 + 1)
    nny, nnm = (ny + (nm == 12), nm % 12 + 1)
    return date(nny, nnm, 1) - timedelta(days=1)


def evaluate(body: dict) -> dict:
    """Mechanical GENIUS checks on a reserve composition report. Pure function, no I/O except none."""
    findings: list[dict] = []

    def add(check: str, ok: bool, detail: str) -> None:
        findings.append({"check": check, "pass": bool(ok), "detail": detail})

    outstanding = body["outstanding_total_usd"]
    reserves = sum(a["value_usd"] for a in body["reserves"])
    ratio = reserves / outstanding if outstanding else float("inf")
    add("one_to_one", reserves >= outstanding,
        f"reserves ${reserves:,.2f} vs outstanding ${outstanding:,.2f} (coverage {ratio:.4f}x)")
    bad = [a for a in body["reserves"] if a["class"] not in ASSET_CLASSES]
    add("permitted_assets", not bad, "all reserve assets are in permitted classes" if not bad else
        "not a permitted reserve class: " + ", ".join(sorted({a["class"] for a in bad})))
    long = [a for a in body["reserves"] if a["class"] in ASSET_CLASSES and ASSET_CLASSES[a["class"]]["max_days"] is not None
            and a.get("max_remaining_maturity_days") is not None
            and a["max_remaining_maturity_days"] > ASSET_CLASSES[a["class"]]["max_days"]]
    missing = [a for a in body["reserves"] if a["class"] in ASSET_CLASSES and ASSET_CLASSES[a["class"]]["max_days"] is not None
               and a.get("max_remaining_maturity_days") is None]
    add("maturity_limits", not long and not missing,
        "maturities within limits" if not long and not missing else
        "; ".join([f"{a['class']} maturity {a['max_remaining_maturity_days']}d exceeds {ASSET_CLASSES[a['class']]['max_days']}d" for a in long]
                  + [f"{a['class']} is missing max_remaining_maturity_days" for a in missing]))
    per_chain = sum(c["outstanding_usd"] for c in body.get("chains", []))
    if body.get("chains"):
        add("chain_breakdown_matches_total", abs(per_chain - outstanding) <= max(1.0, outstanding * 1e-6),
            f"per-chain outstanding ${per_chain:,.2f} vs total ${outstanding:,.2f}")
    return {"findings": findings, "reserves_total_usd": round(reserves, 2), "coverage_ratio": round(ratio, 6) if outstanding else None,
            "all_pass": all(f["pass"] for f in findings)}


class Genius:
    def __init__(self, db_path: str, humans: HumanRegistry, attestor, public_url: str,
                 rpc_call: Callable[[str, dict], Any] | None = None):
        self.humans, self.attestor, self.public_url = humans, attestor, public_url.rstrip("/")
        self._rpc_call = rpc_call
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    # ---- operator ---------------------------------------------------------------------------------

    def create_issuer(self, name: str, paid_days: int = 30) -> dict:
        name = (name or "").strip()[:120]
        if not name or not 1 <= int(paid_days) <= 3660:
            raise GeniusError("issuer name is required and paid_days must be 1-3660")
        iid, key = "giss_" + secrets.token_hex(6), "gnk_" + secrets.token_urlsafe(24)
        with self._lock:
            self._db.execute("INSERT INTO gen_issuers (issuer_id, name, key_hash, paid_until, created_at) VALUES (?,?,?,?,?)",
                             (iid, name, _h(key), _iso(_now() + timedelta(days=int(paid_days))), _iso()))
            self._db.commit()
        return {"issuer_id": iid, "name": name, "issuer_key": key, "note": "Shown once. Send as 'Authorization: Bearer <issuer_key>'."}

    def set_license(self, issuer_id: str, status: str, regulator: str, source_url: str) -> dict:
        if status not in LICENSE_STATUSES:
            raise GeniusError(f"status must be one of {', '.join(LICENSE_STATUSES)}")
        if status in ("permitted", "foreign_comparable", "not_permitted") and not (source_url or "").startswith("https://"):
            raise GeniusError("a regulator source URL (https) is required for this status")
        self._issuer(issuer_id)
        with self._lock:
            self._db.execute("UPDATE gen_issuers SET license_status=?, regulator=?, license_source=?, license_updated_at=? "
                             "WHERE issuer_id=?", (status, (regulator or "")[:120], (source_url or "")[:500], _iso(), issuer_id))
            self._db.commit()
        return {"issuer_id": issuer_id, "license_status": status, "regulator": regulator, "source": source_url}

    def add_coin(self, issuer_id: str, chain: str, address: str, symbol: str, decimals: int = 6) -> dict:
        chain = (chain or "").lower()
        if chain not in RPC:
            raise GeniusError(f"chain must be one of {', '.join(RPC)}")
        if not _ADDR.match(address or ""):
            raise GeniusError("address must be a 0x token contract address")
        self._issuer(issuer_id)
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO gen_coins VALUES (?,?,?,?,?)",
                             (chain, address.lower(), issuer_id, (symbol or "")[:16].upper(), int(decimals)))
            self._db.commit()
        return {"chain": chain, "address": address.lower(), "issuer_id": issuer_id, "symbol": symbol.upper()}

    def extend(self, issuer_id: str, days: int) -> dict:
        iss = self._issuer(issuer_id)
        base = max(_now(), datetime.fromisoformat(iss["paid_until"].replace("Z", "+00:00")))
        until = _iso(base + timedelta(days=int(days)))
        with self._lock:
            self._db.execute("UPDATE gen_issuers SET paid_until=? WHERE issuer_id=?", (until, issuer_id))
            self._db.commit()
        return {"issuer_id": issuer_id, "paid_until": until}

    # ---- issuer -----------------------------------------------------------------------------------------

    def _issuer(self, issuer_id: str) -> dict:
        r = self._db.execute("SELECT * FROM gen_issuers WHERE issuer_id=?", (issuer_id,)).fetchone()
        if not r:
            raise GeniusError("unknown issuer", 404)
        return dict(r)

    def issuer_from_key(self, key: str) -> dict:
        r = self._db.execute("SELECT * FROM gen_issuers WHERE key_hash=?", (_h(key or ""),)).fetchone() if key else None
        if not r:
            raise GeniusError("missing or invalid issuer key", 401)
        return dict(r)

    @staticmethod
    def _require_paid(iss: dict) -> None:
        if iss["paid_until"] < _iso():
            raise GeniusError(f"the {PLAN['plan']} plan for this issuer has ended; renew at {PLAN['pay']}", 402)

    def add_officer(self, iss: dict, name: str, role: str) -> dict:
        self._require_paid(iss)
        role = (role or "").upper()
        if role not in ROLES:
            raise GeniusError("role must be CEO, CFO or EXAMINER (the accounting firm's engagement lead)")
        if not (name or "").strip():
            raise GeniusError("officer name is required")
        oid, tok = "goff_" + secrets.token_hex(6), "genr_" + secrets.token_urlsafe(24)
        with self._lock:
            self._db.execute("INSERT INTO gen_officers (officer_id, issuer_id, name, role, enroll_hash, enroll_until, enroll_nonce)"
                             " VALUES (?,?,?,?,?,?,?)", (oid, iss["issuer_id"], name.strip()[:80], role, _h(tok),
                                                          time.time() + ENROLL_TTL_S, b64u(secrets.token_bytes(32))))
            self._db.commit()
        return {"officer_id": oid, "role": role, "enroll_url": f"{self.public_url}/genius/enroll/{tok}",
                "note": "Give this link to the officer in person or over a channel you already trust; they register a passkey on their own device."}

    def _enrollment(self, tok: str) -> dict:
        r = self._db.execute("SELECT o.*, i.name AS issuer_name FROM gen_officers o JOIN gen_issuers i USING(issuer_id) "
                             "WHERE o.enroll_hash=? AND o.removed=0", (_h(tok or ""),)).fetchone()
        if not r or (r["enroll_until"] or 0) < time.time():
            raise GeniusError("this enroll link is unknown, used or expired", 404)
        return dict(r)

    def enroll_challenge(self, tok: str) -> bytes:
        o = self._enrollment(tok)
        return hashlib.sha256(unb64u(o["enroll_nonce"]) + f"|genius-enroll|{o['officer_id']}".encode()).digest()

    def enroll_options(self, tok: str) -> dict:
        o = self._enrollment(tok)
        return {"officer": o["name"], "role": o["role"], "issuer": o["issuer_name"],
                "create": {"challenge": b64u(self.enroll_challenge(tok)), "rp": {"id": self.humans.rp_id, "name": "Privi GENIUS"},
                           "user": {"id": b64u(o["officer_id"].encode()), "name": o["name"], "displayName": f"{o['name']} ({o['role']})"},
                           "pubKeyCredParams": [{"type": "public-key", "alg": -8}, {"type": "public-key", "alg": -7},
                                                {"type": "public-key", "alg": -257}],
                           "authenticatorSelection": {"residentKey": "preferred", "userVerification": "required"},
                           "attestation": "none", "timeout": 120000}}

    def enroll_finish(self, tok: str, cred: dict) -> dict:
        o = self._enrollment(tok)
        try:
            human_id, _ = self.humans.register_passkey(cred, self.enroll_challenge(tok))
        except HumanError as e:
            raise GeniusError(str(e))
        with self._lock:
            self._db.execute("UPDATE gen_officers SET human_id=?, enrolled_at=?, enroll_hash=NULL, enroll_until=NULL WHERE officer_id=?",
                             (human_id, _iso(), o["officer_id"]))
            self._db.commit()
        return {"enrolled": True, "officer": o["name"], "role": o["role"]}

    # ---- reports ----------------------------------------------------------------------------------------

    def _normalize(self, iss: dict, raw: dict) -> dict:
        period = str(raw.get("period", ""))
        if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", period):
            raise GeniusError("period must be YYYY-MM (the month-end being reported)")
        reserves = []
        for a in raw.get("reserves") or []:
            if not isinstance(a, dict):
                raise GeniusError("each reserve entry must be an object")
            entry = {"class": str(a.get("class", "")), "value_usd": _money(a.get("value_usd"), "reserve value_usd"),
                     "custodian": str(a.get("custodian", ""))[:120], "description": str(a.get("description", ""))[:200]}
            if a.get("max_remaining_maturity_days") is not None:
                entry["max_remaining_maturity_days"] = int(a["max_remaining_maturity_days"])
            reserves.append(entry)
        if not reserves or len(reserves) > 200:
            raise GeniusError("give 1-200 reserve entries")
        chains = []
        for c in raw.get("chains") or []:
            ch, addr = str(c.get("chain", "")).lower(), str(c.get("address", "")).lower()
            row = self._db.execute("SELECT * FROM gen_coins WHERE chain=? AND address=? AND issuer_id=?",
                                   (ch, addr, iss["issuer_id"])).fetchone()
            if not row:
                raise GeniusError(f"{ch}:{addr} is not a registered coin of this issuer (ask Privi to register it)")
            chains.append({"chain": ch, "address": addr, "symbol": row["symbol"], "outstanding_usd": _money(c.get("outstanding_usd"), "chain outstanding_usd")})
        exam = raw.get("examination") or {}
        return {"type": "privi.genius.reserve_report/v1", "issuer": iss["name"], "issuer_id": iss["issuer_id"], "period": period,
                "as_of": str(raw.get("as_of") or f"{period} month-end")[:40],
                "outstanding_total_usd": _money(raw.get("outstanding_total_usd"), "outstanding_total_usd"),
                "reserves": reserves, "chains": chains,
                "examination": {"firm": str(exam.get("firm", ""))[:120], "letter_sha256": str(exam.get("letter_sha256", ""))[:64].lower(),
                                "letter_url": str(exam.get("letter_url", ""))[:500]},
                "redemption_policy_url": str(raw.get("redemption_policy_url", ""))[:500]}

    def _onchain(self, chains: list[dict]) -> list[dict]:
        out = []
        for c in chains:
            row = self._db.execute("SELECT decimals FROM gen_coins WHERE chain=? AND address=?", (c["chain"], c["address"])).fetchone()
            try:
                raw = self._total_supply(c["chain"], c["address"])
                supply = raw / (10 ** row["decimals"])
                diff = abs(supply - c["outstanding_usd"]) / max(c["outstanding_usd"], 1.0)
                out.append({"chain": c["chain"], "address": c["address"], "onchain_supply": round(supply, 2),
                            "reported_usd": c["outstanding_usd"], "matches": diff <= SUPPLY_TOLERANCE, "read_at": _iso()})
            except Exception as e:  # RPC down: record it, don't fail the report
                out.append({"chain": c["chain"], "address": c["address"], "error": f"on-chain read failed: {type(e).__name__}"})
        return out

    def _total_supply(self, chain: str, address: str) -> int:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": address, "data": "0x18160ddd"}, "latest"]}
        if self._rpc_call:
            res = self._rpc_call(RPC[chain], payload)
        else:
            import httpx2
            res = httpx2.post(RPC[chain], json=payload, timeout=15).json()
        return int(res["result"], 16)

    def submit(self, iss: dict, raw: dict) -> dict:
        self._require_paid(iss)
        body = self._normalize(iss, raw)
        checks = evaluate(body)
        rid = "grep_" + secrets.token_hex(8)
        with self._lock:
            ex = self._db.execute("SELECT status FROM gen_reports WHERE issuer_id=? AND period=?", (iss["issuer_id"], body["period"])).fetchone()
            if ex and ex["status"] == "sealed":
                raise GeniusError(f"the {body['period']} report is already sealed; it cannot be replaced", 409)
            self._db.execute("DELETE FROM gen_signoffs WHERE report_id IN (SELECT report_id FROM gen_reports WHERE issuer_id=? AND period=?)",
                             (iss["issuer_id"], body["period"]))
            self._db.execute("DELETE FROM gen_reports WHERE issuer_id=? AND period=?", (iss["issuer_id"], body["period"]))
            self._db.execute("INSERT INTO gen_reports VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (rid, iss["issuer_id"], body["period"], json.dumps(body), json.dumps(checks),
                              b64u(secrets.token_bytes(32)), "awaiting_certification", _iso(), None, None))
            self._db.commit()
        return {"report_id": rid, "period": body["period"], "checks": checks, "status": "awaiting_certification",
                "certify_url": f"{self.public_url}/genius/certify/{rid}",
                "next": "The CEO and CFO each open certify_url on their own enrolled device and certify with their passkey. "
                        "The examiner may also sign. Then POST /genius/v1/reports/{id}/seal."}

    def _report(self, rid: str) -> dict:
        r = self._db.execute("SELECT r.*, i.name AS issuer_name FROM gen_reports r JOIN gen_issuers i USING(issuer_id) WHERE report_id=?",
                             (rid,)).fetchone()
        if not r:
            raise GeniusError("unknown report", 404)
        d = dict(r)
        d["body"], d["checks"] = json.loads(d["body"]), json.loads(d["checks"])
        return d

    def body_hash(self, rid: str) -> str:
        return hashlib.sha256(json.dumps(self._report(rid)["body"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def certify_challenge(self, rid: str, officer_id: str) -> bytes:
        r = self._report(rid)
        return hashlib.sha256(unb64u(r["nonce"]) + f"|genius-certify|{rid}|{officer_id}|{self.body_hash(rid)}".encode()).digest()

    def certify_view(self, rid: str) -> dict:
        r = self._report(rid)
        officers = self._db.execute("SELECT officer_id, name, role, enrolled_at FROM gen_officers WHERE issuer_id=? AND removed=0 "
                                    "AND enrolled_at IS NOT NULL ORDER BY role", (r["issuer_id"],)).fetchall()
        signed = {s["officer_id"] for s in self._db.execute("SELECT officer_id FROM gen_signoffs WHERE report_id=?", (rid,))}
        return {"report_id": rid, "issuer": r["issuer_name"], "period": r["period"], "status": r["status"], "body": r["body"],
                "checks": r["checks"], "body_sha256": self.body_hash(rid),
                "officers": [{**dict(o), "signed": o["officer_id"] in signed} for o in officers]}

    def certify_options(self, rid: str, officer_id: str) -> dict:
        r = self._report(rid)
        if r["status"] == "sealed":
            raise GeniusError("this report is already sealed", 409)
        return {"get": self.humans.get_options(self.certify_challenge(rid, officer_id))}

    def certify(self, rid: str, officer_id: str, cred: dict) -> dict:
        r = self._report(rid)
        if r["status"] == "sealed":
            raise GeniusError("this report is already sealed", 409)
        o = self._db.execute("SELECT * FROM gen_officers WHERE officer_id=? AND issuer_id=? AND removed=0",
                             (officer_id, r["issuer_id"])).fetchone()
        if not o or not o["human_id"]:
            raise GeniusError("unknown or unenrolled officer", 404)
        try:
            human_id, cid = self.humans.verify_assertion(cred, self.certify_challenge(rid, officer_id))
        except HumanError as e:
            raise GeniusError(str(e))
        if not hmac.compare_digest(human_id, o["human_id"]):
            raise GeniusError("this passkey does not belong to that officer", 403)
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO gen_signoffs VALUES (?,?,?,?,?)",
                             (rid, officer_id, o["role"], _iso(), hashlib.sha256(cid.encode()).hexdigest()))
            self._db.commit()
        return {"report_id": rid, "certified_by": o["name"], "role": o["role"], "body_sha256": self.body_hash(rid)}

    def seal(self, iss: dict, rid: str) -> dict:
        self._require_paid(iss)
        r = self._report(rid)
        if r["issuer_id"] != iss["issuer_id"]:
            raise GeniusError("unknown report", 404)
        if r["status"] == "sealed":
            raise GeniusError("already sealed", 409)
        sig = [dict(s) for s in self._db.execute(
            "SELECT s.role, s.signed_at, s.credential_sha256, o.name FROM gen_signoffs s JOIN gen_officers o USING(officer_id) "
            "WHERE s.report_id=? ORDER BY s.role", (rid,))]
        roles = {s["role"] for s in sig}
        if not {"CEO", "CFO"} <= roles:
            raise GeniusError("both the CEO and the CFO must certify before sealing (missing: "
                              + ", ".join(sorted({"CEO", "CFO"} - roles)) + ")", 409)
        onchain = self._onchain(r["body"]["chains"])
        sealed_at = _now()
        due = posting_deadline(r["period"])
        checks = dict(r["checks"])
        findings = list(checks["findings"]) + [
            {"check": "posted_by_deadline", "pass": sealed_at.date() <= due, "detail": f"sealed {sealed_at.date()} vs due {due}"},
            {"check": "ceo_cfo_certified", "pass": True, "detail": "CEO and CFO passkey certifications over the report hash"},
            {"check": "examination_recorded", "pass": bool(r["body"]["examination"]["firm"] and
                                                            (r["body"]["examination"]["letter_sha256"] or "EXAMINER" in roles)),
             "detail": "accounting firm and examination letter hash or examiner signature recorded" if r["body"]["examination"]["firm"]
             else "no accounting firm examination recorded"}]
        for c in onchain:
            findings.append({"check": f"onchain_supply_{c['chain']}", "pass": bool(c.get("matches")),
                             "detail": c.get("error") or f"on-chain {c['onchain_supply']:,.2f} vs reported {c['reported_usd']:,.2f}"})
        checks["findings"], checks["all_pass"] = findings, all(f["pass"] for f in findings)
        record = {"type": "privi.genius.sealed_report/v1", "report_id": rid, "issuer": iss["name"], "issuer_id": iss["issuer_id"],
                  "period": r["period"], "report_sha256": self.body_hash(rid), "report": r["body"], "checks": checks,
                  "certifications": sig, "onchain": onchain, "sealed_at": _iso(sealed_at),
                  "law": {"genius_act_effective": EFFECTIVE_DATE, "dasp_permitted_issuer_deadline": DASP_DEADLINE},
                  "disclaimer": "Mechanical checks and signatures recorded by Privi; not a license, an examination or a legal opinion."}
        att = self.attestor.issue("genius_reserve_report", record)
        with self._lock:
            self._db.execute("UPDATE gen_reports SET status='sealed', sealed_at=?, receipt_id=?, checks=? WHERE report_id=?",
                             (_iso(sealed_at), att["id"], json.dumps(checks), rid))
            self._db.commit()
        return {"report_id": rid, "status": "sealed", "all_pass": checks["all_pass"], "receipt": att,
                "public_url": f"{self.public_url}/genius/reports/{rid}"}

    def public_report(self, rid: str) -> dict:
        r = self._report(rid)
        if r["status"] != "sealed":
            raise GeniusError("not sealed yet", 404)
        return {"report_id": rid, "issuer": r["issuer_name"], "period": r["period"], "sealed_at": r["sealed_at"],
                "checks": r["checks"], "report": r["body"], "receipt": self.attestor.get(r["receipt_id"]),
                "receipt_url": f"{self.public_url}/receipts/{r['receipt_id']}"}

    # ---- the stablecoin check (paid per call) -------------------------------------------------------------

    def check(self, chain: str, address: str) -> dict:
        chain, address = (chain or "").lower(), (address or "").lower()
        today = _now().date().isoformat()
        law = {"genius_act_in_force": today >= EFFECTIVE_DATE, "effective_date": EFFECTIVE_DATE,
               "dasp_deadline": DASP_DEADLINE,
               "dasp_rule": "From 2028-07-18, digital asset service providers may not offer U.S. persons a payment stablecoin "
                            "unless it is issued by a permitted (or qualifying foreign) issuer."}
        coin = self._db.execute("SELECT c.*, i.* FROM gen_coins c JOIN gen_issuers i USING(issuer_id) WHERE chain=? AND address=?",
                                (chain, address)).fetchone()
        if not coin:
            return {"chain": chain, "address": address, "in_privi_registry": False, "verdict": "unknown",
                    "summary": "Not in the Privi GENIUS registry: no recorded issuer status and no sealed reserve report. "
                               "Ask the issuer for its monthly reserve report and license, or treat it as unverified.", "law": law}
        rep = self._db.execute("SELECT * FROM gen_reports WHERE issuer_id=? AND status='sealed' ORDER BY period DESC LIMIT 1",
                               (coin["issuer_id"],)).fetchone()
        latest = None
        if rep:
            checks = json.loads(rep["checks"])
            age = (_now() - datetime.fromisoformat(rep["sealed_at"].replace("Z", "+00:00"))).days
            latest = {"report_id": rep["report_id"], "period": rep["period"], "sealed_at": rep["sealed_at"], "age_days": age,
                      "current": age <= STALE_DAYS, "all_checks_pass": checks["all_pass"],
                      "coverage_ratio": checks.get("coverage_ratio"),
                      "failed_checks": [f["check"] for f in checks["findings"] if not f["pass"]],
                      "public_url": f"{self.public_url}/genius/reports/{rep['report_id']}"}
        lic = coin["license_status"]
        if lic == "not_permitted":
            verdict = "reject"
        elif latest and latest["current"] and latest["all_checks_pass"] and lic in ("permitted", "foreign_comparable"):
            verdict = "pass"
        elif latest and latest["current"] and latest["all_checks_pass"]:
            verdict = "pass_reserves_license_pending"
        else:
            verdict = "caution"
        summary = {"pass": "Licensed issuer (per recorded regulator source) with a current, sealed, fully passing reserve report.",
                   "pass_reserves_license_pending": "Current sealed reserve report passes every check; the issuer's license status is not yet recorded as permitted.",
                   "caution": "No current sealed reserve report that passes every check. Ask the issuer before relying on this coin.",
                   "reject": "The recorded regulator source says this issuer is not permitted."}[verdict]
        return {"chain": chain, "address": address, "symbol": coin["symbol"], "in_privi_registry": True,
                "issuer": {"name": coin["name"], "license_status": lic, "regulator": coin["regulator"] or None,
                           "license_source": coin["license_source"] or None, "license_updated_at": coin["license_updated_at"]},
                "latest_reserve_report": latest, "verdict": verdict, "summary": summary, "law": law,
                "disclaimer": "Evidence recorded by Privi, not a legal determination."}
