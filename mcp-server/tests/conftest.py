import os

# Feature tests were written for the earlier model with free lookup tools; they run with the all-paid gate off.
# tests/test_all_paid.py checks the production default.
os.environ.setdefault("PRIVI_ALL_TOOLS_PAID", "0")
