"""Shared pytest fixtures for ledger-server integration tests.

Keep the existing fixture implementation in test_ledger so tests that import
its server and helper functions use the same setup semantics.
"""

from test_ledger import ledger  # noqa: F401
