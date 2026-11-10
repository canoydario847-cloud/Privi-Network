"""Privi Network on one ledger: every Privi service reports into the Privi Quantum Ledger.

Two links, so nothing depends on a single mechanism:

  * Push. Verify, Anchor, Quantum, Call and Wallet run the shared `ledger_report.py` reporter. Each tool
    call and each state-changing request becomes one event, kept in a local outbox until this server
    accepts it at POST /quantum-ledger/report. Every accepted event is recorded as a ledger entry in the
    Privi Network organization, one stream per service, so it is hash-chained, sealed into the next
    quantum block and shown on Privi Quantum Scan like any other entry.
  * Watch. This server checks every Privi service's health URL. A service going down, coming back or
    changing version is recorded as a ledger entry too, including services that push nothing
    (Discovery, Devnet).

Events carry names, outcomes and hashes only: never request contents, callers or customer data.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .store import Ledger

NETWORK_ORG_ID = "org_9e7309e7309e7309"
NETWORK_ORG_NAME = "Privi Network (service reports)"
SCAN_ORG_ID = "org_5ca95ca95ca95ca9"          # same value as scanner.SCAN_ORG_ID (not imported: scanner is heavy)
SETTLEMENT_HEADER = "x-privi-ledger-settlement"
SERVICE_RE = re.compile(r"^privi-[a-z0-9]{1,24}(-[a-z0-9]{1,24})?$")
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,79}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_EVENTS = 200
MAX_META_BYTES = 2048
STALE_S = 15 * 60                  # a pushing service is "silent" after this long without a heartbeat
DOWN_AFTER_FAILS = 2               # one failed health check is a blip (free services sleep), two is down
ACTION_FOR_KIND = {"tool_call": "tool_call", "payment": "payment", "http": "data_change", "error": "error",
                   "message": "message", "approval": "approval", "decision": "decision"}
OUTCOMES = ("success", "failure", "pending", "blocked")

# "push": the service runs the shared reporter, so it is only linked while its reports keep arriving.
DEFAULT_SERVICES: dict[str, dict[str, Any]] = {
    "privi-verify": {"title": "Privi Verify", "url": "https://privi-verify.onrender.com", "health": "/health", "push": True},
    "privi-anchor": {"title": "Privi Anchor", "url": "https://privi-anchor.onrender.com", "health": "/health", "push": True},
    "privi-quantum": {"title": "Privi Quantum", "url": "https://privi-quantum.onrender.com", "health": "/health", "push": True},
    "privi-call": {"title": "Privi Call", "url": "https://privi-call.onrender.com", "health": "/health", "push": True},
    "privi-wallet": {"title": "Privi Wallet", "url": "https://privi-wallet.onrender.com", "health": "/health", "push": True},
    "privi-discovery": {"title": "Privi Discovery Hub", "url": "https://privi-discovery.onrender.com", "health": "/health"},
    "privi-devnet": {"title": "Privi Devnet", "url": "https://privi-devnet.onrender.com", "health": "/health"},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS network_services (
    service TEXT PRIMARY KEY, title TEXT, url TEXT, first_seen TEXT NOT NULL,
    last_seen TEXT, version TEXT, reports INTEGER NOT NULL DEFAULT 0, last_report_at TEXT, last_entry_hash TEXT,
    health TEXT, health_detail TEXT, health_checked_at TEXT, health_changed_at TEXT,
    fails INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS network_events (
    event_id TEXT NOT NULL, service TEXT NOT NULL, entry_hash TEXT NOT NULL, at TEXT NOT NULL,
    PRIMARY KEY (service, event_id)
);
"""


class NetworkError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime | None = None) -> str:
    return (d or _now()).isoformat(timespec="seconds")


def settlement_token(report_key: str) -> str:
    """What the Ledger sends to Privi Anchor so its own settlement calls are not reported back (see ingest loop
    note in ledger_report.py): a hash of the shared report key, so it cannot be forged without the key."""
    return hashlib.sha256(("privi-ledger-settlement:" + report_key).encode()).hexdigest()


def source_of(org_id: str, stream_id: str) -> str:
    """Which Privi service an entry came from. Never reveals a customer organization or stream."""
    if org_id == NETWORK_ORG_ID:
        return stream_id
    return "privi-scan" if org_id == SCAN_ORG_ID else "privi-ledger"


def load_services() -> dict[str, dict[str, str]]:
    """Services to watch. LEDGER_NETWORK_SERVICES (JSON object) adds to or overrides the defaults; a null value
    removes one."""
    out = {k: dict(v) for k, v in DEFAULT_SERVICES.items()}
    raw = os.getenv("LEDGER_NETWORK_SERVICES", "").strip()
    if raw:
        try:
            for name, spec in json.loads(raw).items():
                if spec is None:
                    out.pop(name, None)
                elif SERVICE_RE.match(name) and isinstance(spec, dict) and str(spec.get("url", "")).startswith("https://"):
                    out[name] = {"title": str(spec.get("title") or name)[:80], "url": str(spec["url"]).rstrip("/"),
                                 "health": str(spec.get("health") or "/health"), "push": bool(spec.get("push"))}
        except (ValueError, AttributeError):
            print("privi-ledger: LEDGER_NETWORK_SERVICES is not valid JSON; using the defaults", flush=True)
    return out


def http_health(url: str, timeout: float = 30.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "PriviLedger/network-watch", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read(65536).decode("utf-8", "replace")
        version = None
        try:
            j = json.loads(body)
            if isinstance(j, dict) and isinstance(j.get("version"), (str, int, float)):
                version = str(j["version"])[:40]
        except ValueError:
            pass
        return {"status": r.status, "version": version}


class Network:
    def __init__(self, ledger: Ledger, services: dict[str, dict[str, str]] | None = None,
                 fetch: Callable[[str], dict[str, Any]] = http_health):
        self.ledger = ledger
        self._db, self._lock = ledger._db, ledger._lock
        self.services = services if services is not None else load_services()
        self._fetch = fetch
        with self._lock:
            self._db.executescript(SCHEMA)
            if not self._db.execute("SELECT 1 FROM orgs WHERE org_id=?", (NETWORK_ORG_ID,)).fetchone():
                # "!" + random: not a SHA-256 hex digest, so no API key can ever open this organization.
                self._db.execute("INSERT INTO orgs (org_id, name, key_hash, created_at) VALUES (?,?,?,?)",
                                 (NETWORK_ORG_ID, NETWORK_ORG_NAME, "!" + secrets.token_hex(32), _iso()))
            for name, spec in self.services.items():
                self._db.execute("INSERT OR IGNORE INTO network_services (service, title, url, first_seen) VALUES (?,?,?,?)",
                                 (name, spec["title"], spec["url"], _iso()))
                self._db.execute("UPDATE network_services SET title=?, url=? WHERE service=?",
                                 (spec["title"], spec["url"], name))
            self._db.commit()

    # ---------------- push: services report events ----------------

    def _touch(self, service: str, version: str | None) -> None:
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO network_services (service, title, first_seen) VALUES (?,?,?)",
                             (service, service, _iso()))
            self._db.execute("UPDATE network_services SET last_seen=?, version=COALESCE(?, version) WHERE service=?",
                             (_iso(), (str(version)[:40] if version else None), service))
            self._db.commit()

    @staticmethod
    def _clean(ev: Any) -> dict[str, Any]:
        if not isinstance(ev, dict):
            raise NetworkError("event must be an object")
        eid = str(ev.get("id") or "")
        if not EVENT_ID_RE.match(eid):
            raise NetworkError("id must be 8-80 characters: letters, digits, . _ : -")
        kind = str(ev.get("kind") or "other").strip().lower()[:32]
        name = " ".join(str(ev.get("name") or "").split())[:200]
        if not name:
            raise NetworkError("name is required")
        outcome = str(ev.get("outcome") or "success")
        if outcome not in OUTCOMES:
            raise NetworkError(f"outcome must be one of: {', '.join(OUTCOMES)}")
        h = str(ev.get("hash") or "").lower().removeprefix("0x")
        if h and not HEX64_RE.match(h):
            raise NetworkError("hash must be a 64-character hex digest")
        meta = ev.get("meta") or {}
        if not isinstance(meta, dict) or any(not isinstance(v, (str, int, float, bool, type(None))) for v in meta.values()):
            raise NetworkError("meta must be a flat object of text, numbers and true/false")
        if len(json.dumps(meta).encode()) > MAX_META_BYTES:
            raise NetworkError(f"meta must be under {MAX_META_BYTES} bytes")
        return {"id": eid, "kind": kind, "name": name, "outcome": outcome, "hash": h or None,
                "at": str(ev.get("at") or "")[:40] or None, "meta": meta}

    def ingest(self, service: str, events: list[Any] | None, version: str | None = None) -> dict[str, Any]:
        """Record a service's events on the ledger. Idempotent per (service, event id): a retried event returns its
        first receipt and is never recorded twice. An empty list is a heartbeat."""
        service = str(service or "").strip().lower()
        if not SERVICE_RE.match(service):
            raise NetworkError("service must look like privi-<name>")
        if service == "privi-ledger" or service == "privi-scan":
            raise NetworkError("the Ledger records its own entries directly")
        events = events or []
        if not isinstance(events, list) or len(events) > MAX_EVENTS:
            raise NetworkError(f"events must be a list of at most {MAX_EVENTS}")
        self._touch(service, version)
        receipts, rejected, new = [], [], 0
        for raw in events:
            try:
                ev = self._clean(raw)
            except NetworkError as e:
                rejected.append({"id": str(raw.get("id"))[:80] if isinstance(raw, dict) else None, "error": str(e)})
                continue
            seen = self._db.execute("SELECT entry_hash FROM network_events WHERE service=? AND event_id=?",
                                    (service, ev["id"])).fetchone()
            if seen:
                receipts.append({"id": ev["id"], "entry_hash": seen["entry_hash"], "duplicate": True})
                continue
            details = {"event_id": ev["id"], "kind": ev["kind"], "meta": ev["meta"]}
            if ev["at"]:
                details["occurred_at"] = ev["at"]
            if ev["hash"]:
                details["request_fingerprint"] = ev["hash"]      # HMAC-SHA256 of the request body, keyed by the reporter
            entry = self.ledger.record(NETWORK_ORG_ID, service, service, ACTION_FOR_KIND.get(ev["kind"], "other"),
                                       f"{ev['kind']}: {ev['name']}", ev["name"], ev["outcome"], details)
            with self._lock:
                self._db.execute("INSERT OR IGNORE INTO network_events VALUES (?,?,?,?)",
                                 (ev["id"], service, entry["entry_hash"], _iso()))
                self._db.execute("UPDATE network_services SET reports=reports+1, last_report_at=?, last_entry_hash=? "
                                 "WHERE service=?", (_iso(), entry["entry_hash"], service))
                self._db.commit()
            receipts.append({"id": ev["id"], "entry_hash": entry["entry_hash"], "seq": entry["seq"]})
            new += 1
        return {"service": service, "accepted": new, "duplicates": sum(1 for r in receipts if r.get("duplicate")),
                "rejected": rejected, "receipts": receipts, "ledger": "Privi Quantum Ledger"}

    # ---------------- watch: the Ledger checks every service ----------------

    def watch_once(self) -> int:
        """Check each service's health URL. Records a ledger entry when a service is first seen, goes down, comes
        back or changes version. Returns how many entries were recorded."""
        recorded = 0
        for name, spec in self.services.items():
            try:
                r = self._fetch(spec["url"].rstrip("/") + spec.get("health", "/health"))
                ok, detail, version = 200 <= int(r.get("status", 0)) < 300, f"HTTP {r.get('status')}", r.get("version")
            except Exception as e:  # any failure to answer counts as a failed check
                ok, detail, version = False, f"{type(e).__name__}: {e}"[:160], None
            row = self._db.execute("SELECT health, fails, version FROM network_services WHERE service=?", (name,)).fetchone()
            was, fails = row["health"], (0 if ok else row["fails"] + 1)
            now = "up" if ok else ("down" if fails >= DOWN_AFTER_FAILS else (was or "checking"))
            version_changed = bool(ok and version and row["version"] and version != row["version"])
            with self._lock:
                self._db.execute("UPDATE network_services SET health=?, health_detail=?, health_checked_at=?, fails=?, "
                                 "version=COALESCE(?, version), health_changed_at=CASE WHEN ? THEN ? ELSE health_changed_at END "
                                 "WHERE service=?", (now, detail, _iso(), fails, version, now != was, _iso(), name))
                self._db.commit()
            if now in ("up", "down") and now != was:
                self.ledger.record(NETWORK_ORG_ID, name, "Privi Ledger network watch", "other" if ok else "error",
                                   f"service.{now}: {spec['title']} is {now}", spec["url"],
                                   "success" if ok else "failure", {"kind": "watch", "health": now, "check": detail,
                                                                    "was": was, "version": version})
                recorded += 1
            elif version_changed:
                self.ledger.record(NETWORK_ORG_ID, name, "Privi Ledger network watch", "other",
                                   f"service.version: {spec['title']} {row['version']} -> {version}", spec["url"],
                                   "success", {"kind": "watch", "from": row["version"], "to": version})
                recorded += 1
        return recorded

    # ---------------- public summary (Privi Quantum Scan) ----------------

    def summary(self) -> dict[str, Any]:
        """Every Privi service and whether it is linked to the ledger. Names, counts and hashes only."""
        cutoff = _iso(_now() - timedelta(seconds=STALE_S))
        streams = {r["stream_id"]: r["n"] for r in self._db.execute(
            "SELECT stream_id, COUNT(*) AS n FROM entries WHERE org_id=? GROUP BY stream_id", (NETWORK_ORG_ID,))}
        own = self._db.execute("SELECT COUNT(*) FROM entries WHERE org_id NOT IN (?,?)",
                               (NETWORK_ORG_ID, SCAN_ORG_ID)).fetchone()[0]
        scan = self._db.execute("SELECT COUNT(*) FROM entries WHERE org_id=?", (SCAN_ORG_ID,)).fetchone()[0]
        out = [{"service": "privi-ledger", "title": "Privi Quantum Ledger", "link": "native", "reporting": True,
                "status": "on the ledger", "entries": own, "health": "up"},
               {"service": "privi-scan", "title": "Privi Scan (MCP trust registry)", "link": "native", "reporting": True,
                "status": "on the ledger", "entries": scan, "health": "up"}]
        for r in self._db.execute("SELECT * FROM network_services ORDER BY service"):
            pushing = bool(r["last_seen"])
            fresh = pushing and r["last_seen"] >= cutoff
            watched = r["service"] in self.services
            expected = watched and bool(self.services[r["service"]].get("push"))
            status = ("reporting" if fresh else "silent" if pushing else "not reporting" if expected
                      else "watched" if watched else "unknown")
            out.append({"service": r["service"], "title": r["title"], "url": r["url"],
                        "link": "push + watch" if pushing and watched else "push" if pushing else "watch",
                        "reporting": bool(fresh), "status": status, "entries": streams.get(r["service"], 0),
                        "reports": r["reports"], "last_report_at": r["last_report_at"], "last_seen": r["last_seen"],
                        "last_entry_hash": r["last_entry_hash"], "version": r["version"],
                        "health": r["health"], "health_checked_at": r["health_checked_at"]})
        linked = sum(1 for s in out if s["status"] in ("on the ledger", "reporting") and s["health"] != "down"
                     or s["status"] == "watched" and s["health"] == "up")
        return {"ledger": "Privi Quantum Ledger", "services": out, "total": len(out), "linked": linked,
                "all_linked": linked == len(out), "stale_after_seconds": STALE_S,
                "note": "Service names, counts and hashes only. Request contents and customers are never shown."}


def http_routes(net: Network, report_key: str) -> list[tuple[str, list[str], Callable]]:
    from starlette.responses import JSONResponse

    def _json(data, status: int = 200):
        return JSONResponse(data, status_code=status, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})

    async def report(request):
        if not report_key:
            return _json({"error": "reporting is not configured on this ledger (LEDGER_REPORT_KEY)"}, 503)
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not token or not hmac.compare_digest(token.encode(), report_key.encode()):
            return _json({"error": "invalid report key"}, 401)
        raw = await request.body()
        if len(raw) > 512_000:
            return _json({"error": "report too large"}, 413)
        try:
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise NetworkError("body must be a JSON object")
            import anyio
            return _json(await anyio.to_thread.run_sync(net.ingest, body.get("service"), body.get("events"),
                                                        body.get("version")))
        except (ValueError, NetworkError) as e:
            return _json({"error": str(e)}, 400)

    async def services(request):
        return _json(net.summary())

    return [("/quantum-ledger/report", ["POST"], report), ("/quantum-ledger/services", ["GET"], services)]
