"""Load demo lots so you can try the tools. Usage: python scripts/seed_demo.py [db_path]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from privi_verify.store import LotStore, seed_demo  # noqa: E402

s = LotStore(sys.argv[1] if len(sys.argv) > 1 else "privi.db")
for lot in seed_demo(s):
    summary = s.summary(lot)
    print(lot, "events:", summary["event_count"], "intact:", summary["integrity"]["valid"])
