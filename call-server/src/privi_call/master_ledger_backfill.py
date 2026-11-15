# Copyright (c) 2026 Privi World Corp. All rights reserved.
"""Read-only, proof-preserving Privi Call history backfill to Privi Master Ledger.

No production deletion and no local write operations. Running without --commit is
a complete source-chain verification + migration estimate (no network requests).
The master Ledger deduplicates identical (service, event id) retries.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .store import GENESIS, PUBLIC_FIELDS, record_hash, sha

HEX64 = re.compile(r"^[0-9a-f]{64}$")
BATCH_MAX = 200
SOURCE = "privi-call"


class BackfillError(ValueError):
    pass


def open_read_only(path: str) -> sqlite3.Connection:
    if not Path(path).is_file():
        raise BackfillError("Call database is missing; no changes made")
    # A true read-only connection prevents modifications to the source call
    # log, credits, paid agent access and checkpoints during verification.
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("BEGIN")  # stable SQLite snapshot across validation and upload
    return conn


def records(conn: sqlite3.Connection) -> Iterator[dict[str, Any]]:
    for row in conn.execute("SELECT * FROM calls ORDER BY seq"):
        yield dict(row)


def verify_original_chain(conn: sqlite3.Connection) -> dict[str, Any]:
    previous, count = GENESIS, 0
    for entry in records(conn):
        count += 1
        public = {key: entry[key] for key in (*PUBLIC_FIELDS, "hash")}
        if (entry["seq"] != count or entry["prev_hash"] != previous or
                record_hash(public) != entry["hash"]):
            raise BackfillError(f"Call log integrity failure at sequence {entry['seq']}; migration aborted")
        try:
            if sha(json.loads(entry["detail"])) != entry["detail_sha256"]:
                raise BackfillError(f"Call detail hash mismatch at sequence {entry['seq']}; migration aborted")
        except (TypeError, json.JSONDecodeError):
            raise BackfillError(f"Invalid call details at sequence {entry['seq']}; migration aborted") from None
        previous = entry["hash"]
    return {"valid": True, "records": count, "last_hash": previous}


def legacy_event(entry: dict[str, Any]) -> dict[str, Any]:
    """A privacy-minimized event: never expose caller, callee, arguments or private details."""
    record_hash_hex = str(entry["hash"])
    if not HEX64.fullmatch(record_hash_hex):
        raise BackfillError("Invalid source call record hash")
    seq = int(entry["seq"])
    if seq < 1:
        raise BackfillError("Invalid source sequence")
    try:
        occurred_at = datetime.fromtimestamp(float(entry["ts"]), timezone.utc).isoformat(timespec="seconds")
    except (ValueError, OverflowError, TypeError):
        raise BackfillError("Invalid timestamp") from None
    channel = str(entry["channel"])
    status = str(entry["status"])
    outcome = ("success" if status in ("ok", "success", "completed")
               else "failure" if status in ("error", "failed")
               else "blocked" if status in ("blocked", "unreachable")
               else "pending")
    return {
        "id": f"clbackfill-{seq:012d}-{record_hash_hex[:16]}",
        "kind": "tool_call" if channel == "agent" else "message",
        "name": "historic_call_receipt",
        "outcome": outcome,
        "hash": record_hash_hex,
        "at": occurred_at,
        "meta": {
            "source": "legacy-call-log",
            "seq": seq,
            "channel": channel if channel in ("agent", "phone") else "other",
            "legacy_hash": record_hash_hex,
            "legacy_prev_hash": str(entry["prev_hash"]),
        },
    }


def post_master(url: str, secret: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url.rstrip("/") + "/quantum-ledger/report",
        data=json.dumps(body, separators=(",", ":")).encode(),
        headers={"Authorization": "Bearer " + secret,
                 "Content-Type": "application/json", "User-Agent": "PriviCallBackfill/1"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read(256_000))


def import_records(conn: sqlite3.Connection, url: str, key: str,
                   *, commit: bool = False, batch_size: int = 100,
                   post: Callable[[str, str, dict[str, Any]], dict[str, Any]] = post_master,
                   limit: int | None = None) -> dict[str, Any]:
    if not 1 <= batch_size <= BATCH_MAX:
        raise BackfillError("batch size must be between 1 and 200")
    if limit is not None and limit <= 0:
        raise BackfillError("limit must be positive")
    checked = verify_original_chain(conn)
    if not commit:
        return {**checked, "mode": "dry-run", "submitted": 0,
                "source_deleted": False, "master": "not contacted"}
    if not key or len(key) < 16 or not url.startswith("https://"):
        raise BackfillError("commit requires an HTTPS master Ledger URL and the configured report key")

    submitted, batches = 0, 0
    current = []
    for item in records(conn):
        if limit is not None and submitted + len(current) >= limit:
            break
        current.append(legacy_event(item))
        if len(current) == batch_size:
            acknowledge(url, key, current, post)
            submitted += len(current)
            batches += 1
            current = []
    if current:
        acknowledge(url, key, current, post)
        submitted += len(current)
        batches += 1
    return {**checked, "mode": "committed", "submitted": submitted, "batches": batches,
            "source_deleted": False, "note": "master event receipt confirmations only; original Call database is unchanged"}


def acknowledge(url: str, key: str, events: list[dict[str, Any]],
                post: Callable[[str, str, dict[str, Any]], dict[str, Any]]) -> None:
    response = post(url, key, {"service": SOURCE, "version": "call-history-backfill-v1", "events": events})
    if not isinstance(response, dict) or response.get("rejected"):
        raise BackfillError("Master Ledger rejected one or more events; no local records were removed")
    by_id = {event["id"] for event in events}
    receipts = response.get("receipts")
    if not isinstance(receipts, list) or len(receipts) < len(by_id):
        raise BackfillError("Incomplete master receipts; safe to retry the same batch")
    seen = set()
    for item in receipts:
        if (not isinstance(item, dict) or item.get("id") not in by_id or
                not HEX64.fullmatch(str(item.get("entry_hash", ""))) or item["id"] in seen):
            raise BackfillError("Invalid master receipt; safe to retry the same batch")
        seen.add(item["id"])
    if seen != by_id:
        raise BackfillError("Missing master receipt for at least one legacy record")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Call history before importing hashed receipts to the Privi Master Ledger")
    parser.add_argument("--db", default=os.getenv("CALL_DB_PATH", "call.db"))
    parser.add_argument("--master-url", default=os.getenv("PRIVI_LEDGER_URL", "https://privi-ledger-aqe5.onrender.com"))
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--commit", action="store_true", help="explicitly send events; default is offline dry-run")
    args = parser.parse_args()
    try:
        conn = open_read_only(args.db)
        try:
            result = import_records(conn, args.master_url, os.getenv("PRIVI_LEDGER_REPORT_KEY", ""),
                                    commit=args.commit, batch_size=args.batch_size, limit=args.limit)
        finally:
            conn.close()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (BackfillError, sqlite3.Error, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error), "source_deleted": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
