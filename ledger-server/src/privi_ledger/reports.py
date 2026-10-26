"""Compliance reports for AI agent activity.

A report summarizes an organization's agent logs for a period: what the agents
did, failures, human approvals, whether every log is intact, and whether each is
anchored on chain (the Privi Devnet). It also lists findings an auditor would ask about.

The report body is hashed (SHA-256 over canonical JSON) and that hash is anchored
on chain (the Privi Devnet) through Privi Anchor. Changing any byte of the report later
changes its hash, so the edited version no longer matches the anchored one.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    report_id    TEXT PRIMARY KEY,
    org_id       TEXT NOT NULL,
    report_hash  TEXT NOT NULL UNIQUE,
    body         TEXT NOT NULL,
    attestation  TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
"""

# Actions that usually call for human sign-off; used for the approval-coverage finding.
SENSITIVE = ("payment", "data_change", "message")


def canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def report_hash(body: dict) -> str:
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_body(ledger, org: dict, onchain: Callable[[str, str, dict], dict],
               since: str | None, until: str | None, streams: list[str] | None) -> dict[str, Any]:
    names = [s["stream_id"] for s in ledger.streams(org["org_id"])]
    if streams:
        names = [s for s in names if s in set(streams)]
    period = {"since": since, "until": until}
    out_streams, totals = [], {"entries": 0, "failures": 0, "blocked": 0, "approvals": 0, "sensitive_actions": 0}
    actions: dict[str, int] = {}
    findings: list[dict] = []

    for sid in names:
        all_entries = ledger.entries(org["org_id"], sid)
        check = ledger.check_chain(all_entries)
        integrity = {"intact": check.valid, "broken_at_seq": check.broken_at_seq, "reason": check.reason,
                     "entry_count": check.entry_count, "head_hash": all_entries[-1]["entry_hash"] if all_entries else None}
        cp = onchain(org["org_id"], sid, integrity)
        sel = [e for e in all_entries
               if (not since or e["recorded_at"] >= since) and (not until or e["recorded_at"] <= until)]
        by_type: dict[str, int] = {}
        for e in sel:
            by_type[e["action_type"]] = by_type.get(e["action_type"], 0) + 1
            actions[e["action_type"]] = actions.get(e["action_type"], 0) + 1
        fails = [e for e in sel if e["outcome"] == "failure"]
        blocked = [e for e in sel if e["outcome"] == "blocked"]
        approvals = by_type.get("approval", 0)
        sensitive = sum(by_type.get(t, 0) for t in SENSITIVE)
        totals["entries"] += len(sel); totals["failures"] += len(fails); totals["blocked"] += len(blocked)
        totals["approvals"] += approvals; totals["sensitive_actions"] += sensitive

        out_streams.append({
            "stream_id": sid, "entries_in_period": len(sel),
            "first_recorded_at": sel[0]["recorded_at"] if sel else None,
            "last_recorded_at": sel[-1]["recorded_at"] if sel else None,
            "actors": sorted({e["actor"] for e in sel}),
            "action_counts": by_type,
            "failures": [{"seq": e["seq"], "summary": e["summary"], "entry_hash": e["entry_hash"]} for e in fails],
            "blocked": len(blocked), "human_approvals": approvals, "sensitive_actions": sensitive,
            "integrity": {k: integrity[k] for k in ("intact", "broken_at_seq", "reason", "entry_count", "head_hash")},
            "onchain_checkpoint": {k: cp.get(k) for k in ("anchored", "seq", "tx_hash", "block_number",
                                                          "matches_current_record") if k in cp},
        })

        if not integrity["intact"]:
            findings.append({"severity": "critical", "stream_id": sid,
                             "finding": f"Log integrity failed at entry {integrity['broken_at_seq']}: {integrity['reason']}"})
        if not cp.get("anchored"):
            findings.append({"severity": "medium", "stream_id": sid,
                             "finding": "Log is not yet anchored on chain; integrity relies on Privi's database"})
        elif cp.get("seq") and cp["seq"] < integrity["entry_count"]:
            findings.append({"severity": "low", "stream_id": sid,
                             "finding": f"{integrity['entry_count'] - cp['seq']} newest entr(y/ies) not yet covered by an on-chain checkpoint"})
        if fails:
            findings.append({"severity": "low", "stream_id": sid,
                             "finding": f"{len(fails)} agent action(s) failed in this period; review recommended"})
        if sensitive and not approvals:
            findings.append({"severity": "medium", "stream_id": sid,
                             "finding": f"{sensitive} sensitive action(s) (payments, data changes, messages) with no human approval recorded"})

    if not out_streams:
        findings.append({"severity": "info", "stream_id": None, "finding": "No agent activity logged for this organization"})

    return {
        "report_type": "privi-ledger/ai-agent-activity",
        "version": 1,
        "organization": {"org_id": org["org_id"], "name": org["name"]},
        "period": period,
        "generated_at": _now(),
        "generated_by": "Privi Ledger",
        "totals": {**totals, "streams": len(out_streams), "action_counts": actions},
        "findings": findings,
        "status": ("attention_required" if any(f["severity"] in ("critical", "medium") for f in findings)
                   else "clean"),
        "streams": out_streams,
        "method": ("Entries are hash-chained (SHA-256 over each entry and the previous entry's hash). "
                   "Stream heads and this report's hash are anchored on chain (the Privi Devnet, until the Privi mainnet) via Privi Anchor."),
    }


def to_markdown(body: dict, attestation: dict) -> str:
    o, t = body["organization"], body["totals"]
    p = body["period"]
    lines = [
        f"# AI Agent Activity Report: {o['name']}",
        "",
        f"Organization `{o['org_id']}` · Period {p['since'] or 'start'} to {p['until'] or 'now'} · "
        f"Generated {body['generated_at']} by {body['generated_by']}",
        "",
        f"**Status: {body['status'].replace('_', ' ')}**",
        "",
        "## Summary",
        "",
        "| Agent logs | Actions | Failures | Blocked | Human approvals | Sensitive actions |",
        "|---|---|---|---|---|---|",
        f"| {t['streams']} | {t['entries']} | {t['failures']} | {t['blocked']} | {t['approvals']} | {t['sensitive_actions']} |",
        "",
        "## Findings",
        "",
    ]
    lines += [f"- **{f['severity'].upper()}**{' (' + f['stream_id'] + ')' if f['stream_id'] else ''}: {f['finding']}"
              for f in body["findings"]] or ["- None"]
    lines += ["", "## Agent logs", "", "| Log | Actions | Intact | On chain | Actors |", "|---|---|---|---|---|"]
    for s in body["streams"]:
        cp = s["onchain_checkpoint"]
        chain = f"yes, block {cp.get('block_number')}" if cp.get("anchored") else "not yet"
        lines.append(f"| {s['stream_id']} | {s['entries_in_period']} | {'yes' if s['integrity']['intact'] else 'NO'} "
                     f"| {chain} | {', '.join(s['actors'])} |")
    lines += ["", "## Verification", "",
              f"Report hash (SHA-256 of the canonical report body): `{attestation['report_hash']}`", ""]
    if attestation.get("anchored"):
        chain = f" (chain {attestation['chain_id']})" if attestation.get("chain_id") else ""
        lines.append(f"Anchored on chain (the Privi Devnet){chain} in transaction "
                     f"`{attestation['tx_hash']}`, block {attestation.get('block_number')}. Check it with Privi Anchor "
                     f"`anchor_verify` using the hash, transaction and proof in this report's attestation, or with "
                     f"Privi Ledger `ledger_verify_report`.")
    else:
        lines.append(f"Not anchored on chain: {attestation.get('reason', 'anchoring not configured')}.")
    lines += ["", f"_{body['method']}_"]
    return "\n".join(lines)


class ReportStore:
    def __init__(self, db: sqlite3.Connection, lock: threading.Lock):
        self._db, self._lock = db, lock
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def save(self, org_id: str, body: dict, attestation: dict) -> str:
        rid = "rpt_" + secrets.token_hex(8)
        with self._lock:
            self._db.execute("INSERT INTO reports VALUES (?,?,?,?,?,?)",
                             (rid, org_id, attestation["report_hash"], canonical(body), json.dumps(attestation), _now()))
            self._db.commit()
        return rid

    def get(self, report_id: str, org_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM reports WHERE report_id=? AND org_id=?", (report_id, org_id)).fetchone()
        if not r:
            return None
        return {"report_id": r["report_id"], "body": json.loads(r["body"]), "attestation": json.loads(r["attestation"])}

    def by_hash(self, h: str) -> dict | None:
        r = self._db.execute("SELECT * FROM reports WHERE report_hash=?", (h,)).fetchone()
        if not r:
            return None
        return {"report_id": r["report_id"], "org_id": r["org_id"], "created_at": r["created_at"],
                "attestation": json.loads(r["attestation"])}
