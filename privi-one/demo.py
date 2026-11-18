"""Privi ONE prelaunch simulator: SmartRoute + Guard + CallProof-style policy + receipt.

Offline only. No AI requests, purchases, token operations, external actions or
ledger submissions. Uses existing Privi Guard engine source without modifying it.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "ledger-server/src/privi_ledger/guard_engine.py"
SCHEMA = "privi-one-prelaunch-v1"
DEMO_OPTIONS = [
    {"id": "budget", "name": "Synthetic budget model", "cost_cents": 3, "quality": 78, "latency_ms": 1200, "reliability": 96},
    {"id": "balanced", "name": "Synthetic balanced model", "cost_cents": 8, "quality": 91, "latency_ms": 800, "reliability": 99},
    {"id": "premium", "name": "Synthetic premium model", "cost_cents": 19, "quality": 96, "latency_ms": 1600, "reliability": 99},
]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def guard_engine():
    if not GUARD_PATH.is_file():
        raise RuntimeError("Privi Guard engine unavailable; refusing to proceed")
    spec = importlib.util.spec_from_file_location("privi_one_guard_engine", GUARD_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load Privi Guard")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def choose(options, *, quality_min=85, reliability_min=98, latency_max_ms=2000):
    """Sort eligible quotes by price, then quality/reliability/latency.
    Cost/quality numbers are synthetic comparisons; no provider pricing is fetched.
    """
    if not isinstance(options, list) or not options:
        raise ValueError("Options required")
    if not all(type(x) is int for x in (quality_min, reliability_min, latency_max_ms)):
        raise ValueError("Thresholds must be integers")
    if not (0 <= quality_min <= 100 and 0 <= reliability_min <= 100 and latency_max_ms > 0):
        raise ValueError("Invalid routing thresholds")
    ids = set()
    for x in options:
        if not isinstance(x, dict) or not isinstance(x.get("id"), str) or not x["id"] or x["id"] in ids:
            raise ValueError("Unique option IDs required")
        ids.add(x["id"])
        for name in ("cost_cents", "quality", "reliability", "latency_ms"):
            if type(x.get(name)) is not int or x[name] < 0:
                raise ValueError("Each quote needs nonnegative integer " + name)
        if x["quality"] > 100 or x["reliability"] > 100:
            raise ValueError("Scores cannot exceed 100")
    eligible = [x for x in options if x["quality"] >= quality_min
                and x["reliability"] >= reliability_min and x["latency_ms"] <= latency_max_ms]
    eligible.sort(key=lambda x: (x["cost_cents"], -x["quality"], -x["reliability"], x["latency_ms"], x["id"]))
    return eligible[0] if eligible else None


def evaluate(task, *, tool, allowed_tools, budget_cents, approved,
             options=None, baseline_id="premium", quality_min=85,
             reliability_min=98, latency_max_ms=2000,
             secret=None):
    """Create a policy decision and locally HMAC-authenticated synthetic receipt.

    Caller is *not* authenticated: this is a local illustration only.
    Approval is a test input, NOT real independent human approval.
    """
    if not isinstance(task, str) or not task.strip() or len(task) > 10000:
        raise ValueError("Task must contain 1..10000 characters")
    if not isinstance(tool, str) or not tool or not isinstance(allowed_tools, list):
        raise ValueError("Invalid tool allowance")
    if type(budget_cents) is not int or budget_cents < 0 or type(approved) is not bool:
        raise ValueError("Budget must be a nonnegative integer; approval must be boolean")
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < 32:
        raise ValueError("A locally supplied HMAC key of 32+ bytes is required")
    quotes = DEMO_OPTIONS if options is None else options
    selected = choose(quotes, quality_min=quality_min, reliability_min=reliability_min,
                      latency_max_ms=latency_max_ms)
    baseline = next((x for x in quotes if isinstance(x, dict) and x.get("id") == baseline_id), None)
    # Guard scans inbound task; don't store task or raw findings in the receipt.
    guard = guard_engine().inspect(task, direction="inbound")
    reasons = []
    if guard["verdict"] != "allow":
        reasons.append("guard_" + guard["verdict"])
    if tool not in allowed_tools:
        reasons.append("tool_not_authorized")
    if not approved:
        reasons.append("human_approval_missing")
    if selected is None:
        reasons.append("no_quality_qualified_route")
    elif selected["cost_cents"] > budget_cents:
        reasons.append("budget_exceeded")
    permitted = not reasons
    saved = max(0, baseline["cost_cents"] - selected["cost_cents"]) if (baseline and selected) else None
    receipt = {
        "schema": SCHEMA,
        "mode": "PRELAUNCH_SIMULATION_NO_EXTERNAL_EXECUTION",
        "task_sha256": hashlib.sha256(task.encode()).hexdigest(),
        "guard": {"engine": guard["engine"], "verdict": guard["verdict"],
                  "risk": guard["risk"], "input_sha256": guard["input_sha256"],
                  "finding_codes": [f["code"] for f in guard["findings"]]},
        "policy": {"tool": tool, "tool_allowed": tool in allowed_tools,
                   "approval_supplied": approved, "budget_cents": budget_cents},
        "routing": {"quotes": quotes, "selected_id": selected["id"] if selected else None,
                    "baseline_id": baseline_id, "estimated_savings_cents": saved,
                    "quality_min": quality_min, "reliability_min": reliability_min,
                    "latency_max_ms": latency_max_ms},
        "decision": "SIMULATED_APPROVAL" if permitted else "DENIED",
        "denial_reasons": reasons,
        "execution": "NOT_ATTEMPTED",
        "actual_charge_cents": 0,
        "ledger": "NOT_SUBMITTED",
        "token": "NOT_USED",
    }
    return {"receipt": receipt, "digest_sha256": digest(receipt),
            "auth": {"algorithm": "HMAC-SHA256-DEMO-ONLY",
                     "mac": hmac.new(secret, canonical(receipt), hashlib.sha256).hexdigest()}}


def verify(envelope, secret):
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < 32:
        return False
    if not isinstance(envelope, dict) or not isinstance(envelope.get("receipt"), dict):
        return False
    if envelope["receipt"].get("schema") != SCHEMA:
        return False
    auth = envelope.get("auth")
    if not isinstance(auth, dict) or auth.get("algorithm") != "HMAC-SHA256-DEMO-ONLY":
        return False
    mac = hmac.new(secret, canonical(envelope["receipt"]), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, str(auth.get("mac", ""))) and hmac.compare_digest(
        digest(envelope["receipt"]), str(envelope.get("digest_sha256", "")))


def main():
    p = argparse.ArgumentParser(description="Privi ONE offline prelaunch demonstration")
    p.add_argument("--task", default="Summarize a synthetic non-sensitive report")
    p.add_argument("--tool", default="report_summary")
    p.add_argument("--allow-tool", action="append", default=["report_summary"])
    p.add_argument("--budget-cents", type=int, default=10)
    p.add_argument("--approve", action="store_true", help="synthetic approval input; not an authenticated human")
    p.add_argument("--output", help="write JSON receipt to a local file")
    p.add_argument("--verify", help="verify an existing local JSON receipt instead of creating one")
    args = p.parse_args()
    raw = os.environ.get("PRIVI_ONE_DEMO_HMAC_KEY", "")
    if len(raw.encode()) < 32:
        p.error("Set PRIVI_ONE_DEMO_HMAC_KEY to a random 32+ byte local test secret")
    key = raw.encode()
    if args.verify:
        with open(args.verify, encoding="utf-8") as f:
            good = verify(json.load(f), key)
        print(json.dumps({"verified": good, "mode": "LOCAL_HMAC_ONLY"}))
        return 0 if good else 2
    out = evaluate(args.task, tool=args.tool, allowed_tools=args.allow_tool,
                   budget_cents=args.budget_cents, approved=args.approve, secret=key)
    serialized = json.dumps(out, indent=2)
    if args.output:
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if out["receipt"]["decision"] == "SIMULATED_APPROVAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
