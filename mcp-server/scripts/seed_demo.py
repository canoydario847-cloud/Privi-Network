"""Load demo lots so you can try the tools. Usage: python scripts/seed_demo.py [db_path]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from privi_verify.store import LotStore  # noqa: E402

db = sys.argv[1] if len(sys.argv) > 1 else "privi.db"
s = LotStore(db)

if not s.exists("DEMO-STEEL-0001"):
    s.record_event("DEMO-STEEL-0001", "received", "Port Huron, MI", "Demo Steel Supply",
                   product="Cold-rolled steel coil", quantity="2 t", notes="Heat no. DEMO-H123")
    s.record_event("DEMO-STEEL-0001", "produced", "Port Huron, MI", "Demo Fabrication",
                   product="Bracket A-12", quantity="800 pcs")
    s.record_event("DEMO-STEEL-0001", "inspected", "Port Huron, MI", "Demo Fabrication QA",
                   notes="Dimensional check passed, sample 32/800")
    s.record_event("DEMO-STEEL-0001", "shipped", "Port Huron, MI", "Demo Fabrication",
                   quantity="800 pcs", notes="To Detroit-area assembler")

if not s.exists("DEMO-FOOD-0001"):
    s.record_event("DEMO-FOOD-0001", "received", "St. Clair County, MI", "Demo Farm",
                   product="Romaine lettuce", quantity="40 cases")
    s.record_event("DEMO-FOOD-0001", "shipped", "St. Clair County, MI", "Demo Cold Storage",
                   quantity="40 cases")

for lot in ("DEMO-STEEL-0001", "DEMO-FOOD-0001"):
    summary = s.summary(lot)
    print(lot, "events:", summary["event_count"], "intact:", summary["integrity"]["valid"])
