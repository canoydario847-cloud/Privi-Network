"""Self-serve plans.

free        - created by ledger_signup; up to LEDGER_FREE_MONTHLY entries per calendar month (UTC)
pro         - free + paid_until in the future: unlimited entries; bought 30 days at a time with x402
enterprise  - created by the admin route or bootstrap; unlimited, billed outside the server

An expired pro plan falls back to free limits; nothing is deleted.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

PRO_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


class Plans:
    def __init__(self, ledger):
        self.ledger, self._db, self._lock = ledger, ledger._db, ledger._lock
        self.free_monthly = int(os.getenv("LEDGER_FREE_MONTHLY", "500"))
        self.signups_per_hour = int(os.getenv("LEDGER_SIGNUPS_PER_HOUR", "20"))
        self._signups: deque[float] = deque()
        with self._lock:
            cols = {r[1] for r in self._db.execute("PRAGMA table_info(orgs)").fetchall()}
            if "plan" not in cols:
                self._db.execute("ALTER TABLE orgs ADD COLUMN plan TEXT NOT NULL DEFAULT 'enterprise'")
            if "paid_until" not in cols:
                self._db.execute("ALTER TABLE orgs ADD COLUMN paid_until TEXT")
            self._db.commit()

    def signup(self, name: str) -> dict:
        now = time.monotonic()
        with self._lock:
            while self._signups and now - self._signups[0] > 3600:
                self._signups.popleft()
            if len(self._signups) >= self.signups_per_hour:
                raise ValueError("too many sign-ups right now; try again later")
            self._signups.append(now)
        org = self.ledger.create_org(name)
        with self._lock:
            self._db.execute("UPDATE orgs SET plan='free' WHERE org_id=?", (org["org_id"],))
            self._db.commit()
        return org

    def _row(self, org_id: str):
        return self._db.execute("SELECT plan, paid_until FROM orgs WHERE org_id=?", (org_id,)).fetchone()

    def usage_this_month(self, org_id: str) -> int:
        start = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self._db.execute("SELECT COUNT(*) FROM entries WHERE org_id=? AND recorded_at>=?",
                                (org_id, _iso(start))).fetchone()[0]

    def status(self, org_id: str) -> dict:
        r = self._row(org_id)
        plan, paid_until = (r["plan"], r["paid_until"]) if r else ("free", None)
        active_pro = plan in ("free", "pro") and paid_until and paid_until > _iso(_now())
        effective = "enterprise" if plan == "enterprise" else ("pro" if active_pro else "free")
        used = self.usage_this_month(org_id)
        limit = None if effective in ("pro", "enterprise") else self.free_monthly
        return {"plan": effective, "paid_until": paid_until if plan != "enterprise" else None,
                "entries_this_month": used, "monthly_limit": limit,
                "remaining_this_month": None if limit is None else max(0, limit - used)}

    def can_write(self, org_id: str, n: int = 1) -> tuple[bool, dict]:
        st = self.status(org_id)
        return (st["monthly_limit"] is None or st["entries_this_month"] + n <= st["monthly_limit"]), st

    def extend_pro(self, org_id: str, days: int = PRO_DAYS) -> dict:
        with self._lock:
            r = self._row(org_id)
            current = r["paid_until"] if r and r["paid_until"] and r["paid_until"] > _iso(_now()) else None
            start = datetime.fromisoformat(current) if current else _now()
            new_until = _iso(start + timedelta(days=days))
            plan = r["plan"] if r and r["plan"] == "enterprise" else "pro"
            self._db.execute("UPDATE orgs SET plan=?, paid_until=? WHERE org_id=?", (plan, new_until, org_id))
            self._db.commit()
        return self.status(org_id)
