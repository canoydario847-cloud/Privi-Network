import os

# Feature tests predate the all-paid rule; tests/test_all_paid.py checks the production default.
os.environ.setdefault("ANCHOR_ALL_TOOLS_PAID", "0")
