#!/usr/bin/env python3
"""privi: use your Privi Ledger from the terminal.

  privi login                         save your organization API key (asked privately)
  privi status                        organization, plan, usage and streams
  privi record STREAM TYPE "SUMMARY"  record an action (TYPE: tool_call, data_access, data_change,
                                      payment, message, decision, approval, error, other)
  privi log STREAM [-n 20]            show the latest entries and the integrity check
  privi receipt ENTRY_HASH            confirm an entry exists and prove it is in the transparency log
  privi report                        issue a sealed compliance report
  privi pdf REPORT_ID [-o file.pdf]   download a report as PDF
  privi passport [STREAM]             issue a Privi Passport (whole organization if no stream)
  privi kya ADDRESS                   Know-Your-Agent check for a wallet
  privi bundle STREAM [-o file]       export an offline evidence bundle
  privi check-bundle FILE             verify a bundle offline (downloads Privi's verifier once)
  privi tree                          latest signed tree head of the transparency log
  privi stats                         public tool-call counts

Only Python 3.9+ is needed. Settings live in ~/.config/privi/config.json (readable only by you).
Set PRIVI_LEDGER_URL to use a different Ledger.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://privi-ledger.onrender.com"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "privi" / "config.json"
ACTION_TYPES = ("tool_call", "data_access", "data_change", "payment", "message", "decision", "approval", "error", "other")


# ---------------------------------------------------------------- config

def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2))
    CONFIG.chmod(stat.S_IRUSR | stat.S_IWUSR)


def base_url() -> str:
    return (os.environ.get("PRIVI_LEDGER_URL") or load_config().get("url") or DEFAULT_URL).rstrip("/")


def api_key(required: bool = True) -> str:
    key = os.environ.get("PRIVI_API_KEY") or load_config().get("api_key", "")
    if required and not key:
        die("no organization key yet. Run: privi login")
    return key


def die(msg: str, code: int = 1) -> None:
    print(f"privi: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- transport

def call(tool: str, args: dict | None = None, auth: bool = True) -> dict:
    """Call a Privi Ledger MCP tool over streamable HTTP (JSON-RPC tools/call)."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": args or {}}}).encode()
    req = urllib.request.Request(f"{base_url()}/mcp", data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "User-Agent": "privi-cli/1"})
    if auth:
        req.add_header("Authorization", f"Bearer {api_key()}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        die(f"Ledger answered HTTP {e.code}: {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        die(f"could not reach {base_url()} ({e.reason}). Check your connection; Render may be waking up.")
    if raw.lstrip().startswith("event:") or raw.lstrip().startswith("data:"):
        raw = next((l[5:].strip() for l in raw.splitlines() if l.startswith("data:")), "{}")
    msg = json.loads(raw)
    if "error" in msg:
        die(msg["error"].get("message", str(msg["error"])))
    res = msg.get("result", {})
    data = res.get("structuredContent")
    if data is None:
        text = next((c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"), "{}")
        try:
            data = json.loads(text)
        except ValueError:
            data = {"text": text}
    if res.get("isError"):
        die(data.get("error") or json.dumps(data))
    return data


def get(path: str) -> dict:
    try:
        with urllib.request.urlopen(f"{base_url()}{path}", timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        die(f"Ledger answered HTTP {e.code}: {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        die(f"could not reach {base_url()} ({e.reason})")


def show(data, keys: list[str] | None = None) -> None:
    if keys:
        w = max(len(k) for k in keys)
        for k in keys:
            if k in data and data[k] is not None:
                v = data[k]
                print(f"{k.replace('_', ' '):<{w}}  {json.dumps(v) if isinstance(v, (dict, list)) else v}")
    else:
        print(json.dumps(data, indent=2))


# ---------------------------------------------------------------- commands

def cmd_login(a):
    key = getpass.getpass("Organization API key (input hidden): ").strip()
    if len(key) < 20:
        die("that does not look like an organization key")
    cfg = load_config()
    cfg["api_key"] = key
    if a.url:
        cfg["url"] = a.url.rstrip("/")
    save_config(cfg)
    os.environ["PRIVI_API_KEY"] = key
    p = call("ledger_plan")
    print(f"Signed in as {p['organization']} ({p['org_id']}), {p['plan']} plan. Key saved to {CONFIG}")


def cmd_status(a):
    p = call("ledger_plan")
    s = call("ledger_list_streams")
    print(f"{p['organization']}  ({p['org_id']})  on {base_url()}")
    lim = p.get("monthly_limit")
    print(f"plan: {p['plan']}   entries this month: {p['entries_this_month']}" + (f" of {lim}" if lim else ""))
    if p.get("paid_until"):
        print(f"paid until: {p['paid_until']}")
    print("\nstreams:")
    for st in s.get("streams", []):
        print(f"  {st['stream_id']:<32} {st['entries']:>6} entries   last {st['last_recorded_at']}")
    if not s.get("streams"):
        print("  none yet. Try: privi record my-agent tool_call \"First action\"")


def cmd_record(a):
    if a.type not in ACTION_TYPES:
        die(f"TYPE must be one of: {', '.join(ACTION_TYPES)}")
    args = {"stream_id": a.stream, "actor": a.actor or getpass.getuser(), "action_type": a.type,
            "summary": a.summary, "resource": a.resource or "", "outcome": a.outcome}
    if a.details:
        try:
            args["details"] = json.loads(a.details)
        except ValueError:
            die("--details must be a JSON object")
    e = call("ledger_record_action", args)["entry"]
    print(f"recorded #{e['seq']} in {e['stream_id']}\nreceipt: {e['entry_hash']}")


def cmd_log(a):
    d = call("ledger_read_stream", {"stream_id": a.stream, "limit": 500})
    entries = d["entries"][-a.n:]
    for e in entries:
        print(f"#{e['seq']:<5} {e['recorded_at'][:19]}  {e['action_type']:<12} {e['outcome']:<8} {e['summary']}")
    i = d["integrity"]
    oc = i.get("onchain_checkpoint") or {}
    print(f"\nintegrity: {'INTACT' if i['intact'] else 'BROKEN at #' + str(i['broken_at_seq']) + ': ' + str(i['reason'])}"
          f"   {i['entry_count']} entries"
          + (f"   anchored on chain at block {oc.get('block_number')}" if oc.get("anchored") else ""))


def cmd_receipt(a):
    r = call("ledger_check_receipt", {"entry_hash": a.entry_hash}, auth=False)
    if not r.get("found"):
        die("no entry with that hash")
    show(r, ["org_id", "stream_id", "seq", "recorded_at", "action_type", "outcome"])
    p = call("ledger_inclusion_proof", {"entry_hash": a.entry_hash}, auth=False)
    th = p["signed_tree_head"]["tree_head"]
    print(f"\ntransparency log: leaf {p['leaf_index']} of {p['tree_size']}, proof "
          f"{'VERIFIED' if p['verified_here'] else 'FAILED'} against root {th['root_hash'][:16]}…")


def cmd_report(a):
    r = call("ledger_compliance_report", {})
    at = r["attestation"]
    print(f"report {r['report_id']}: {r['report']['status']}")
    print(f"hash {at['report_hash']}")
    print("anchored on chain at block " + str(at.get("block_number")) if at.get("anchored") else "not anchored yet")
    print(f"PDF: privi pdf {r['report_id']}")


def cmd_pdf(a):
    r = call("ledger_report_pdf", {"report_id": a.report_id})
    out = Path(a.o or f"{a.report_id}.pdf")
    out.write_bytes(base64.b64decode(r["pdf_base64"]))
    print(f"saved {out} ({r['bytes']} bytes)")


def cmd_passport(a):
    r = call("passport_issue", {"stream_id": a.stream} if a.stream else {})
    print(f"passport {r['passport_id']}: grade {r['grade']}, {r['score']}/1000")
    if r.get("attestation", {}).get("anchored"):
        print(f"anchored at Privi block {r['attestation'].get('block_number')}")
    print(f"share: {r['public_url']}")


def cmd_kya(a):
    d = get(f"/kya/{a.address}?min_score=0")
    if d.get("allow"):
        print(f"ALLOWED: {d['organization']}, grade {d['current_grade']} ({d['current_score']}), proof: {d['proof']}")
    else:
        print("NOT ALLOWED: " + "; ".join(d.get("reasons", [])))


def cmd_bundle(a):
    b = call("ledger_evidence_bundle", {"stream_id": a.stream})
    out = Path(a.o or f"{a.stream}-evidence.json")
    out.write_text(json.dumps(b, indent=2))
    print(f"saved {out}: {b['bundle']['chain']['entry_count']} entries, signed Ed25519 + ML-DSA-87")
    print(f"verify offline: privi check-bundle {out}")


def cmd_check_bundle(a):
    v = CONFIG.parent / "verify_bundle.py"
    if not v.exists():
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{base_url()}/tools/verify_bundle.py", timeout=60) as r:
            v.write_bytes(r.read())
    sys.exit(subprocess.call([sys.executable, str(v), a.file]))


def cmd_tree(a):
    d = get("/log/sth")
    th = d["tree_head"]
    print(f"entries: {th['tree_size']}\nroot:    {th['root_hash']}\nsigned:  {th['timestamp']} (Ed25519 + ML-DSA-87)")
    if d.get("anchor"):
        print(f"anchored: Privi block {d['anchor'].get('block_number')}")


def cmd_stats(a):
    d = get("/stats")
    print(f"tool calls: {d['total_tool_calls']} all time, {d['last_30_days']} in 30 days, {d['today']} today")
    for t, c in list(d["by_tool_all_time"].items())[:15]:
        print(f"  {t:<30} {c}")


def main():
    ap = argparse.ArgumentParser(prog="privi", description="Use your Privi Ledger from the terminal.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n")[1])
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("login"); p.add_argument("--url"); p.set_defaults(f=cmd_login)
    sp.add_parser("status").set_defaults(f=cmd_status)
    p = sp.add_parser("record"); p.add_argument("stream"); p.add_argument("type"); p.add_argument("summary")
    p.add_argument("--resource"); p.add_argument("--outcome", default="success",
                                                 choices=["success", "failure", "pending", "blocked"])
    p.add_argument("--details", help="JSON object"); p.add_argument("--actor"); p.set_defaults(f=cmd_record)
    p = sp.add_parser("log"); p.add_argument("stream"); p.add_argument("-n", type=int, default=20); p.set_defaults(f=cmd_log)
    p = sp.add_parser("receipt"); p.add_argument("entry_hash"); p.set_defaults(f=cmd_receipt)
    sp.add_parser("report").set_defaults(f=cmd_report)
    p = sp.add_parser("pdf"); p.add_argument("report_id"); p.add_argument("-o"); p.set_defaults(f=cmd_pdf)
    p = sp.add_parser("passport"); p.add_argument("stream", nargs="?"); p.set_defaults(f=cmd_passport)
    p = sp.add_parser("kya"); p.add_argument("address"); p.set_defaults(f=cmd_kya)
    p = sp.add_parser("bundle"); p.add_argument("stream"); p.add_argument("-o"); p.set_defaults(f=cmd_bundle)
    p = sp.add_parser("check-bundle"); p.add_argument("file"); p.set_defaults(f=cmd_check_bundle)
    sp.add_parser("tree").set_defaults(f=cmd_tree)
    sp.add_parser("stats").set_defaults(f=cmd_stats)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
