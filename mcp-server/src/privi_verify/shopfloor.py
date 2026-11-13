"""Privi ChainFlow Shop Floor: five quality records small manufacturers keep on paper today.

- Recall Trace               link lots to the lots they were made from; one call lists every lot a bad batch touched
- Certificate of Conformance issue a certificate for a shipment, tied to the lot's record; the buyer checks it
- Lot Documents              attach mill test reports and inspection reports to a lot by fingerprint
- Non-Conformance Reports    open, disposition and close NCRs against a lot
- Gauge Calibration          gauges, their calibration certificates, and what is due

Writes need a manufacturer key. Every write also adds an event to the lot's hash chain, so it is covered by
the on-chain checkpoints. Privi stores fingerprints (SHA-256) of documents, never the files.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Callable

from mcp.server.mcpserver import Context
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from .store import LotStore, normalize_lot

SCHEMA = """
CREATE TABLE IF NOT EXISTS sf_links (
    parent_lot TEXT NOT NULL, child_lot TEXT NOT NULL, quantity TEXT NOT NULL DEFAULT '', linked_at TEXT NOT NULL,
    PRIMARY KEY (parent_lot, child_lot));
CREATE TABLE IF NOT EXISTS sf_cocs (
    coc_id TEXT PRIMARY KEY, lot_code TEXT NOT NULL, body TEXT NOT NULL, body_hash TEXT NOT NULL UNIQUE,
    issued_at TEXT NOT NULL, revoked_at TEXT, revoke_reason TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS sf_documents (
    sha256 TEXT NOT NULL, lot_code TEXT NOT NULL, doc_type TEXT NOT NULL, issuer TEXT NOT NULL,
    reference TEXT NOT NULL DEFAULT '', attached_at TEXT NOT NULL, record_hash TEXT NOT NULL,
    PRIMARY KEY (sha256, lot_code));
CREATE TABLE IF NOT EXISTS sf_ncrs (
    ncr_id TEXT PRIMARY KEY, lot_code TEXT NOT NULL, defect TEXT NOT NULL, severity TEXT NOT NULL,
    quantity_affected TEXT NOT NULL DEFAULT '', opened_by TEXT NOT NULL, opened_at TEXT NOT NULL,
    status TEXT NOT NULL, disposition TEXT, corrective_action TEXT, closed_by TEXT, closed_at TEXT);
CREATE TABLE IF NOT EXISTS sf_gauges (
    gauge_id TEXT PRIMARY KEY, description TEXT NOT NULL, interval_days INTEGER NOT NULL, location TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, retired INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sf_calibrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, gauge_id TEXT NOT NULL, calibrated_at TEXT NOT NULL, calibrated_by TEXT NOT NULL,
    certificate_sha256 TEXT NOT NULL, result TEXT NOT NULL);
"""

HEX64 = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DOC_TYPES = ("mill_test_report", "material_certificate", "inspection_report", "first_article_inspection",
             "heat_treat_certificate", "plating_certificate", "test_report", "other")
SEVERITIES = ("minor", "major", "critical")
DISPOSITIONS = ("use_as_is", "rework", "repair", "scrap", "return_to_supplier")
MAX_TRACE = 2000

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)


class ShopError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def _when(value: str | None, what: str) -> datetime:
    if not value:
        return _now()
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ShopError(f"{what} must be an ISO 8601 date or date-time") from None
    d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    if d > _now() + timedelta(minutes=5):
        raise ShopError(f"{what} cannot be in the future")
    return d


def _hex(v: Any, what: str) -> str:
    s = str(v or "").strip().lower()
    if not HEX64.match(s):
        raise ShopError(f"{what} must be a SHA-256 fingerprint (64 hex characters)")
    return s


def _txt(v: Any, what: str, lo: int, hi: int) -> str:
    s = str(v or "").strip()
    if not lo <= len(s) <= hi:
        raise ShopError(f"{what} must be {lo}-{hi} characters")
    return s


def canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ShopFloor:
    def __init__(self, store: LotStore, public_url: str = ""):
        self.store, self._db, self._lock, self.public_url = store, store._db, store._lock, public_url
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def _lot(self, lot_code: str) -> str:
        try:
            code = normalize_lot(lot_code)
        except ValueError as e:
            raise ShopError(str(e)) from None
        if not self.store.exists(code):
            raise ShopError(f"lot '{code}' has no events yet; record one first with privi_record_event")
        return code

    # ---- 1. Recall Trace -------------------------------------------------

    def link(self, parent_lot: str, child_lot: str, actor: str, location: str, quantity: str = "") -> dict:
        parent, actor, location = self._lot(parent_lot), _txt(actor, "actor", 2, 160), _txt(location, "location", 2, 160)
        try:
            child = normalize_lot(child_lot)
        except ValueError as e:
            raise ShopError(str(e)) from None
        if parent == child:
            raise ShopError("a lot cannot be made from itself")
        if parent in self._walk(child, "down"):
            raise ShopError(f"{child} is already upstream of {parent}; that link would make a loop")
        if self._db.execute("SELECT 1 FROM sf_links WHERE parent_lot=? AND child_lot=?", (parent, child)).fetchone():
            raise ShopError("those lots are already linked")
        qty = str(quantity or "").strip()[:60]
        with self._lock:
            self._db.execute("INSERT INTO sf_links VALUES (?,?,?,?)", (parent, child, qty, _iso(_now())))
            self._db.commit()
        a = self.store.record_event(parent, "transferred", location, actor, quantity=qty, notes=f"Consumed into lot {child}")
        b = self.store.record_event(child, "produced", location, actor, quantity=qty, notes=f"Made from lot {parent}")
        return {"linked": True, "parent_lot": parent, "child_lot": child, "quantity": qty,
                "parent_event": a["record_hash"], "child_event": b["record_hash"]}

    def _walk(self, start: str, direction: str) -> dict[str, int]:
        col_from, col_to = ("parent_lot", "child_lot") if direction == "down" else ("child_lot", "parent_lot")
        seen, frontier, depth = {}, [start], 0
        while frontier and len(seen) < MAX_TRACE:
            depth += 1
            nxt = []
            for lot in frontier:
                for r in self._db.execute(f"SELECT {col_to} AS x FROM sf_links WHERE {col_from}=?", (lot,)):
                    if r["x"] not in seen and r["x"] != start:
                        seen[r["x"]] = depth
                        nxt.append(r["x"])
            frontier = nxt
        return seen

    def _brief(self, lot: str, depth: int) -> dict:
        evs = self.store.events(lot)
        last = evs[-1]
        return {"lot_code": lot, "steps_away": depth, "product": next((e["product"] for e in reversed(evs) if e["product"]), ""),
                "last_event": last["event_type"], "last_location": last["location"], "last_actor": last["actor"],
                "shipped": any(e["event_type"] == "shipped" for e in evs),
                "recalled": any(e["event_type"] == "recalled" for e in evs)}

    def trace(self, lot_code: str) -> dict:
        lot = self._lot(lot_code)
        down, up = self._walk(lot, "down"), self._walk(lot, "up")
        made_into = [self._brief(k, d) for k, d in sorted(down.items(), key=lambda x: (x[1], x[0]))]
        made_from = [self._brief(k, d) for k, d in sorted(up.items(), key=lambda x: (x[1], x[0]))]
        return {"lot_code": lot, "this_lot": self._brief(lot, 0), "made_into": made_into, "made_from": made_from,
                "affected_if_recalled": [x["lot_code"] for x in made_into],
                "already_shipped": [x["lot_code"] for x in made_into if x["shipped"]],
                "not_yet_recalled": [x["lot_code"] for x in made_into if not x["recalled"]],
                "truncated": len(down) >= MAX_TRACE or len(up) >= MAX_TRACE}

    # ---- 2. Certificate of Conformance -------------------------------------

    def coc_issue(self, lot_code: str, customer: str, specification: str, signer: str, signer_title: str, location: str,
                  quantity: str = "", purchase_order: str = "", part_number: str = "", statement: str = "") -> dict:
        lot = self._lot(lot_code)
        evs = self.store.events(lot)
        if any(e["event_type"] == "recalled" for e in evs):
            raise ShopError("this lot is recalled; a certificate cannot be issued for it")
        if not self.store.check_chain(evs).valid:
            raise ShopError("this lot's record history is not intact; fix that before certifying it")
        if n := self._db.execute("SELECT COUNT(*) AS n FROM sf_ncrs WHERE lot_code=? AND status='open'", (lot,)).fetchone()["n"]:
            raise ShopError(f"this lot has {n} open non-conformance report(s); close them first")
        coc_id, signer = "coc_" + secrets.token_hex(6), _txt(signer, "signer", 2, 160)
        docs = [dict(r) for r in self._db.execute(
            "SELECT doc_type, sha256, issuer, reference FROM sf_documents WHERE lot_code=? ORDER BY attached_at", (lot,))]
        body = {"coc_id": coc_id, "lot_code": lot, "customer": _txt(customer, "customer", 2, 160),
                "specification": _txt(specification, "specification", 2, 300), "part_number": str(part_number or "").strip()[:80],
                "purchase_order": str(purchase_order or "").strip()[:80], "quantity": str(quantity or "").strip()[:60],
                "statement": str(statement or "").strip()[:1000] or
                "We certify that the items in this lot were produced, inspected and tested in accordance with the "
                "specification above and conform to its requirements.",
                "signed_by": signer, "title": _txt(signer_title, "signer_title", 2, 120), "issued_at": _iso(_now()),
                "lot_record": {"events": len(evs), "head_fingerprint": evs[-1]["record_hash"]},
                "supporting_documents": docs}
        h = hashlib.sha256(canon(body).encode()).hexdigest()
        with self._lock:
            self._db.execute("INSERT INTO sf_cocs (coc_id, lot_code, body, body_hash, issued_at) VALUES (?,?,?,?,?)",
                             (coc_id, lot, canon(body), h, body["issued_at"]))
            self._db.commit()
        ev = self.store.record_event(lot, "inspected", _txt(location, "location", 2, 160), signer,
                                     notes=f"Certificate of Conformance {coc_id} issued to {body['customer']} (sha256 {h})")
        return {"certificate": body, "certificate_json": canon(body), "certificate_sha256": h,
                "lot_event": ev["record_hash"], "verify_url": f"{self.public_url}/coc/{coc_id}"}

    def coc_verify(self, coc_id: str = "", certificate_json: str = "") -> dict:
        if certificate_json:
            h = hashlib.sha256(certificate_json.encode()).hexdigest()
            r = self._db.execute("SELECT * FROM sf_cocs WHERE body_hash=?", (h,)).fetchone()
            if not r:
                return {"valid": False, "certificate_sha256": h,
                        "reason": "no certificate with this exact content was issued; it may have been edited"}
        else:
            r = self._db.execute("SELECT * FROM sf_cocs WHERE coc_id=?", (str(coc_id or "").strip(),)).fetchone()
            if not r:
                return {"valid": False, "reason": "no such certificate"}
        body, evs = json.loads(r["body"]), self.store.events(r["lot_code"])
        intact = self.store.check_chain(evs).valid
        covered = any(e["record_hash"] == body["lot_record"]["head_fingerprint"] for e in evs)
        recalled = any(e["event_type"] == "recalled" for e in evs)
        reasons = [t for ok, t in ((not r["revoked_at"], f"revoked: {r['revoke_reason']}"),
                                   (intact, "the lot's record history has been altered"),
                                   (covered, "the lot record this certificate points to no longer exists"),
                                   (not recalled, "the lot has been recalled since the certificate was issued")) if not ok]
        return {"valid": not reasons, "reasons": reasons, "certificate": body, "certificate_sha256": r["body_hash"],
                "revoked_at": r["revoked_at"], "lot_recalled": recalled, "lot_history_intact": intact}

    def coc_revoke(self, coc_id: str, reason: str, actor: str, location: str) -> dict:
        r = self._db.execute("SELECT * FROM sf_cocs WHERE coc_id=?", (str(coc_id or "").strip(),)).fetchone()
        if not r:
            raise ShopError("no such certificate")
        if r["revoked_at"]:
            raise ShopError("certificate is already revoked")
        reason = _txt(reason, "reason", 3, 500)
        with self._lock:
            self._db.execute("UPDATE sf_cocs SET revoked_at=?, revoke_reason=? WHERE coc_id=?", (_iso(_now()), reason, r["coc_id"]))
            self._db.commit()
        self.store.record_event(r["lot_code"], "inspected", _txt(location, "location", 2, 160), _txt(actor, "actor", 2, 160),
                                notes=f"Certificate of Conformance {r['coc_id']} revoked: {reason}"[:500])
        return self.coc_verify(r["coc_id"])

    # ---- 3. Lot Documents --------------------------------------------------

    def attach(self, lot_code: str, doc_type: str, sha256: str, issuer: str, actor: str, location: str,
               reference: str = "") -> dict:
        lot = self._lot(lot_code)
        if doc_type not in DOC_TYPES:
            raise ShopError("doc_type must be one of: " + ", ".join(DOC_TYPES))
        sha, issuer = _hex(sha256, "sha256"), _txt(issuer, "issuer", 2, 160)
        if self._db.execute("SELECT 1 FROM sf_documents WHERE sha256=? AND lot_code=?", (sha, lot)).fetchone():
            raise ShopError("that document is already attached to this lot")
        ref = str(reference or "").strip()[:120]
        ev = self.store.record_event(lot, "inspected", _txt(location, "location", 2, 160), _txt(actor, "actor", 2, 160),
                                     notes=f"Document attached: {doc_type} from {issuer} {ref} (sha256 {sha})"[:500])
        with self._lock:
            self._db.execute("INSERT INTO sf_documents VALUES (?,?,?,?,?,?,?)",
                             (sha, lot, doc_type, issuer, ref, _iso(_now()), ev["record_hash"]))
            self._db.commit()
        return {"attached": True, "lot_code": lot, "doc_type": doc_type, "sha256": sha, "issuer": issuer,
                "reference": ref, "lot_event": ev["record_hash"]}

    def documents(self, lot_code: str) -> dict:
        lot = self._lot(lot_code)
        docs = [dict(r) for r in self._db.execute(
            "SELECT doc_type, sha256, issuer, reference, attached_at, record_hash FROM sf_documents WHERE lot_code=? "
            "ORDER BY attached_at", (lot,))]
        return {"lot_code": lot, "documents": docs, "missing_common": [t for t in ("material_certificate", "inspection_report")
                                                                       if t not in {d["doc_type"] for d in docs}
                                                                       and not (t == "material_certificate" and
                                                                                any(d["doc_type"] == "mill_test_report" for d in docs))]}

    def document_check(self, sha256: str) -> dict:
        sha = _hex(sha256, "sha256")
        rows = [dict(r) for r in self._db.execute(
            "SELECT lot_code, doc_type, issuer, reference, attached_at FROM sf_documents WHERE sha256=? ORDER BY attached_at", (sha,))]
        return {"sha256": sha, "known": bool(rows), "attached_to": rows,
                "reason": None if rows else "no lot has a document with this fingerprint; the file may have been altered"}

    # ---- 4. Non-Conformance Reports ----------------------------------------

    def ncr_open(self, lot_code: str, defect: str, severity: str, opened_by: str, location: str,
                 quantity_affected: str = "") -> dict:
        lot = self._lot(lot_code)
        if severity not in SEVERITIES:
            raise ShopError("severity must be one of: " + ", ".join(SEVERITIES))
        defect, opened_by = _txt(defect, "defect", 3, 400), _txt(opened_by, "opened_by", 2, 160)
        ncr_id, qty = "ncr_" + secrets.token_hex(5), str(quantity_affected or "").strip()[:60]
        self.store.record_event(lot, "inspected", _txt(location, "location", 2, 160), opened_by, quantity=qty,
                                notes=f"NCR {ncr_id} opened ({severity}): {defect}"[:500])
        with self._lock:
            self._db.execute("INSERT INTO sf_ncrs (ncr_id, lot_code, defect, severity, quantity_affected, opened_by, "
                             "opened_at, status) VALUES (?,?,?,?,?,?,?,'open')",
                             (ncr_id, lot, defect, severity, qty, opened_by, _iso(_now())))
            self._db.commit()
        return self.ncr(ncr_id)

    def ncr(self, ncr_id: str) -> dict:
        r = self._db.execute("SELECT * FROM sf_ncrs WHERE ncr_id=?", (str(ncr_id or "").strip(),)).fetchone()
        if not r:
            raise ShopError("no such non-conformance report")
        d = dict(r)
        end = datetime.fromisoformat(d["closed_at"]) if d["closed_at"] else _now()
        d["days_open"] = round((end - datetime.fromisoformat(d["opened_at"])).total_seconds() / 86400, 1)
        return d

    def ncr_close(self, ncr_id: str, disposition: str, corrective_action: str, closed_by: str, location: str) -> dict:
        d = self.ncr(ncr_id)
        if d["status"] != "open":
            raise ShopError("this report is already closed")
        if disposition not in DISPOSITIONS:
            raise ShopError("disposition must be one of: " + ", ".join(DISPOSITIONS))
        action, closed_by = _txt(corrective_action, "corrective_action", 3, 1000), _txt(closed_by, "closed_by", 2, 160)
        self.store.record_event(d["lot_code"], "inspected", _txt(location, "location", 2, 160), closed_by,
                                notes=f"NCR {d['ncr_id']} closed: {disposition}. {action}"[:500])
        with self._lock:
            self._db.execute("UPDATE sf_ncrs SET status='closed', disposition=?, corrective_action=?, closed_by=?, "
                             "closed_at=? WHERE ncr_id=?", (disposition, action, closed_by, _iso(_now()), d["ncr_id"]))
            self._db.commit()
        return self.ncr(d["ncr_id"])

    def ncr_list(self, lot_code: str = "", status: str = "") -> dict:
        if status and status not in ("open", "closed"):
            raise ShopError("status must be open or closed")
        q, args = "SELECT ncr_id FROM sf_ncrs WHERE 1=1", []
        if lot_code:
            q, args = q + " AND lot_code=?", args + [self._lot(lot_code)]
        if status:
            q, args = q + " AND status=?", args + [status]
        rows = [self.ncr(r["ncr_id"]) for r in self._db.execute(q + " ORDER BY opened_at DESC LIMIT 200", args)]
        return {"reports": rows, "open": sum(1 for r in rows if r["status"] == "open"),
                "open_critical": sum(1 for r in rows if r["status"] == "open" and r["severity"] == "critical")}

    # ---- 5. Gauge Calibration ----------------------------------------------

    def gauge_save(self, gauge_id: str, description: str, interval_days: int, location: str = "", retired: bool = False) -> dict:
        gid = str(gauge_id or "").strip()
        if not ID_RE.match(gid):
            raise ShopError("gauge_id must be 1-64 letters, digits, dot, dash or underscore")
        if not isinstance(interval_days, int) or not 1 <= interval_days <= 3650:
            raise ShopError("interval_days must be 1-3650 (365 = yearly)")
        desc = _txt(description, "description", 2, 200)
        with self._lock:
            old = self._db.execute("SELECT created_at FROM sf_gauges WHERE gauge_id=?", (gid,)).fetchone()
            self._db.execute("INSERT OR REPLACE INTO sf_gauges VALUES (?,?,?,?,?,?)",
                             (gid, desc, interval_days, str(location or "").strip()[:160],
                              old["created_at"] if old else _iso(_now()), int(bool(retired))))
            self._db.commit()
        return self.gauge(gid)

    def gauge_calibrated(self, gauge_id: str, certificate_sha256: str, calibrated_by: str, result: str = "pass",
                         calibrated_at: str | None = None) -> dict:
        gid = str(gauge_id or "").strip()
        if not self._db.execute("SELECT 1 FROM sf_gauges WHERE gauge_id=?", (gid,)).fetchone():
            raise ShopError("no such gauge; add it first with chainflow_gauge_save")
        if result not in ("pass", "fail", "adjusted"):
            raise ShopError("result must be pass, fail or adjusted")
        with self._lock:
            self._db.execute("INSERT INTO sf_calibrations (gauge_id, calibrated_at, calibrated_by, certificate_sha256, result)"
                             " VALUES (?,?,?,?,?)", (gid, _iso(_when(calibrated_at, "calibrated_at")),
                                                     _txt(calibrated_by, "calibrated_by", 2, 160),
                                                     _hex(certificate_sha256, "certificate_sha256"), result))
            self._db.commit()
        return self.gauge(gid)

    def gauge(self, gauge_id: str, now: datetime | None = None) -> dict:
        g = self._db.execute("SELECT * FROM sf_gauges WHERE gauge_id=?", (str(gauge_id or "").strip(),)).fetchone()
        if not g:
            raise ShopError("no such gauge")
        last = self._db.execute("SELECT calibrated_at, calibrated_by, certificate_sha256, result FROM sf_calibrations "
                                "WHERE gauge_id=? ORDER BY calibrated_at DESC, id DESC LIMIT 1", (g["gauge_id"],)).fetchone()
        now, out = now or _now(), {k: g[k] for k in ("gauge_id", "description", "interval_days", "location")}
        if g["retired"]:
            return {**out, "status": "retired", "usable": False, "last_calibration": dict(last) if last else None}
        if not last:
            return {**out, "status": "never_calibrated", "usable": False, "last_calibration": None}
        due = datetime.fromisoformat(last["calibrated_at"]) + timedelta(days=g["interval_days"])
        days = (due - now).total_seconds() / 86400
        status = "failed_last_calibration" if last["result"] == "fail" else "overdue" if days < 0 else \
            "due_soon" if days <= 30 else "in_calibration"
        return {**out, "status": status, "usable": status in ("in_calibration", "due_soon"), "due_at": _iso(due),
                "days_left": round(days, 1), "last_calibration": dict(last)}

    def gauges_due(self) -> dict:
        rows = [self.gauge(r["gauge_id"]) for r in self._db.execute("SELECT gauge_id FROM sf_gauges ORDER BY gauge_id")]
        rows = [r for r in rows if r["status"] != "retired"]
        counts = {s: sum(1 for r in rows if r["status"] == s) for s in
                  ("overdue", "failed_last_calibration", "never_calibrated", "due_soon", "in_calibration")}
        return {"as_of": _iso(_now()), "counts": counts, "do_not_use": [r["gauge_id"] for r in rows if not r["usable"]],
                "gauges": rows}


def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))], structured_content=data, is_error=is_error)


Lot = Annotated[str, Field(description="Lot or batch code")]
Where = Annotated[str, Field(description="Where it happened, e.g. 'Plant 2, Port Huron MI'")]
Sha = Annotated[str, Field(description="SHA-256 fingerprint of the document (64 hex characters); the file stays with you")]


def register(mcp, shop: ShopFloor, can_write: Callable[[Context], bool]) -> None:
    denied = _result({"error": "a manufacturer key is required (Authorization: Bearer <key>)"}, is_error=True)

    def run(fn, *a, **kw) -> CallToolResult:
        try:
            return _result(fn(*a, **kw))
        except (ShopError, ValueError) as e:
            return _result({"error": str(e)}, is_error=True)

    def write(ctx, fn, *a, **kw) -> CallToolResult:
        return run(fn, *a, **kw) if can_write(ctx) else denied

    @mcp.tool(title="ChainFlow: link a lot to what it was made from", annotations=WRITE)
    def chainflow_link_lots(parent_lot: Annotated[str, Field(description="The lot that was used up (material, component)")],
                            child_lot: Annotated[str, Field(description="The lot that was made from it")],
                            actor: str, location: Where, ctx: Context,
                            quantity: Annotated[str, Field(description="How much of the parent went in, e.g. '400 kg'")] = "") -> CallToolResult:
        """Record that one lot was made from another, so a recall can follow the material. Adds an event to both
        lots' histories. Manufacturers only."""
        return write(ctx, shop.link, parent_lot, child_lot, actor, location, quantity)

    @mcp.tool(title="ChainFlow: recall trace", annotations=READ)
    def chainflow_recall_trace(lot_code: Lot) -> CallToolResult:
        """Everything a lot touched: the lots made from it (and from those), which have already shipped, which
        are not yet recalled, and the lots it was itself made from. The list a recall starts with."""
        return run(shop.trace, lot_code)

    @mcp.tool(title="ChainFlow: issue a Certificate of Conformance", annotations=WRITE)
    def chainflow_coc_issue(lot_code: Lot, customer: str,
                            specification: Annotated[str, Field(description="Drawing, standard or spec and revision, e.g. 'DWG A-12 rev C, ASTM A36'")],
                            signer: Annotated[str, Field(description="Person certifying")], signer_title: str, location: Where,
                            ctx: Context, quantity: str = "", purchase_order: str = "", part_number: str = "",
                            statement: Annotated[str, Field(description="Your own certification wording; a standard sentence is used if empty")] = "") -> CallToolResult:
        """Issue a Certificate of Conformance for a lot. It names the customer, spec and signer, lists the lot's
        attached documents and points at the lot's record, so the buyer can check it has not been edited.
        Refused for recalled lots, lots with open non-conformance reports, or altered histories. Manufacturers only."""
        return write(ctx, shop.coc_issue, lot_code, customer, specification, signer, signer_title, location,
                     quantity, purchase_order, part_number, statement)

    @mcp.tool(title="ChainFlow: check a Certificate of Conformance", annotations=READ)
    def chainflow_coc_verify(coc_id: Annotated[str, Field(description="The certificate ID (coc_...)")] = "",
                             certificate_json: Annotated[str, Field(description="Or the exact certificate_json you were sent")] = "") -> CallToolResult:
        """Check a Certificate of Conformance a supplier sent you: that it was issued as shown, is not revoked,
        and that its lot has not been recalled or altered since."""
        if not coc_id and not certificate_json:
            return _result({"error": "give coc_id or certificate_json"}, is_error=True)
        return run(shop.coc_verify, coc_id, certificate_json)

    @mcp.tool(title="ChainFlow: revoke a Certificate of Conformance", annotations=WRITE)
    def chainflow_coc_revoke(coc_id: str, reason: str, actor: str, location: Where, ctx: Context) -> CallToolResult:
        """Revoke a certificate issued in error. Manufacturers only."""
        return write(ctx, shop.coc_revoke, coc_id, reason, actor, location)

    @mcp.tool(title="ChainFlow: attach a document to a lot", annotations=WRITE)
    def chainflow_attach_document(lot_code: Lot, doc_type: Annotated[str, Field(description="|".join(DOC_TYPES))],
                                  sha256: Sha, issuer: Annotated[str, Field(description="Who issued it, e.g. the mill or lab")],
                                  actor: str, location: Where, ctx: Context,
                                  reference: Annotated[str, Field(description="Heat number, report number or similar")] = "") -> CallToolResult:
        """Attach a mill test report, material certificate or inspection report to a lot by fingerprint.
        Manufacturers only."""
        return write(ctx, shop.attach, lot_code, doc_type, sha256, issuer, actor, location, reference)

    @mcp.tool(title="ChainFlow: a lot's documents", annotations=READ)
    def chainflow_documents(lot_code: Lot) -> CallToolResult:
        """The documents attached to a lot (type, issuer, reference, fingerprint) and common ones still missing."""
        return run(shop.documents, lot_code)

    @mcp.tool(title="ChainFlow: check a document", annotations=READ)
    def chainflow_document_check(sha256: Sha) -> CallToolResult:
        """Check that a document you were handed is the one attached to a lot, and see which lot."""
        return run(shop.document_check, sha256)

    @mcp.tool(title="ChainFlow: open a non-conformance report", annotations=WRITE)
    def chainflow_ncr_open(lot_code: Lot, defect: Annotated[str, Field(description="What is wrong")],
                           severity: Annotated[str, Field(description="|".join(SEVERITIES))], opened_by: str,
                           location: Where, ctx: Context, quantity_affected: str = "") -> CallToolResult:
        """Open a non-conformance report (NCR) against a lot. While it is open, no Certificate of Conformance can
        be issued for that lot. Manufacturers only."""
        return write(ctx, shop.ncr_open, lot_code, defect, severity, opened_by, location, quantity_affected)

    @mcp.tool(title="ChainFlow: close a non-conformance report", annotations=WRITE)
    def chainflow_ncr_close(ncr_id: str, disposition: Annotated[str, Field(description="|".join(DISPOSITIONS))],
                            corrective_action: Annotated[str, Field(description="Root cause and what was done about it")],
                            closed_by: str, location: Where, ctx: Context) -> CallToolResult:
        """Close an NCR with its disposition and corrective action. Manufacturers only."""
        return write(ctx, shop.ncr_close, ncr_id, disposition, corrective_action, closed_by, location)

    @mcp.tool(title="ChainFlow: non-conformance reports", annotations=READ)
    def chainflow_ncr_list(ctx: Context, lot_code: Annotated[str, Field(description="Limit to one lot")] = "",
                           status: Annotated[str, Field(description="open or closed; empty for both")] = "") -> CallToolResult:
        """List non-conformance reports with days open, for one lot or all. Manufacturers only."""
        return write(ctx, shop.ncr_list, lot_code, status)

    @mcp.tool(title="ChainFlow: add or update a gauge", annotations=WRITE)
    def chainflow_gauge_save(gauge_id: Annotated[str, Field(description="Your gauge ID or serial, e.g. MIC-014")],
                             description: str, interval_days: Annotated[int, Field(description="Calibration interval in days (365 = yearly)")],
                             ctx: Context, location: str = "", retired: bool = False) -> CallToolResult:
        """Add a measuring tool (micrometer, caliper, CMM, torque wrench) to the calibration list. Manufacturers only."""
        return write(ctx, shop.gauge_save, gauge_id, description, interval_days, location, retired)

    @mcp.tool(title="ChainFlow: record a calibration", annotations=WRITE)
    def chainflow_gauge_calibrated(gauge_id: str, certificate_sha256: Sha,
                                   calibrated_by: Annotated[str, Field(description="Lab or person")], ctx: Context,
                                   result: Annotated[str, Field(description="pass | adjusted | fail")] = "pass",
                                   calibrated_at: Annotated[str | None, Field(description="When (ISO 8601). Default: now")] = None) -> CallToolResult:
        """Record a gauge's calibration with the fingerprint of its certificate. Manufacturers only."""
        return write(ctx, shop.gauge_calibrated, gauge_id, certificate_sha256, calibrated_by, result, calibrated_at)

    @mcp.tool(title="ChainFlow: gauges due for calibration", annotations=READ)
    def chainflow_gauges_due(ctx: Context, gauge_id: Annotated[str, Field(description="One gauge; empty for the whole list")] = "") -> CallToolResult:
        """Which gauges are overdue, failed, never calibrated or due within 30 days, and which must not be used.
        Manufacturers only."""
        return write(ctx, shop.gauge, gauge_id) if gauge_id else write(ctx, shop.gauges_due)

    @mcp.custom_route("/coc/{coc_id}", methods=["GET"], include_in_schema=False)
    async def coc_public(request: Request) -> JSONResponse:
        v = shop.coc_verify(request.path_params["coc_id"])
        return JSONResponse(v, status_code=200 if "certificate" in v else 404,
                            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})
