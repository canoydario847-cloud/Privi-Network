"""Shared pytest fixtures for ledger-server integration tests.

Keep the existing fixture implementation in test_ledger so tests that import
its server and helper functions use the same setup semantics.
"""

import os

# Feature tests below were written for the earlier free-plan model; they run with the all-paid gate off.
# tests/test_all_paid.py checks the production default (every tool paid unless on Pro/enterprise).
os.environ.setdefault("LEDGER_ALL_TOOLS_PAID", "0")

from test_ledger import ledger  # noqa: E402,F401
