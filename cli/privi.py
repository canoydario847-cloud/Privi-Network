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

Real time (Privi Live):
  privi watch [--trust-only] [--address 0x..] [--replay N]   live stream of your audit tail and the trust network
  privi kill [STREAM|*] [--reason "..."]                     stop an agent at once (spending, gateways, rooms)
  privi resume [STREAM|*]                                    lift the kill switch
  privi ask "ACTION" --approver 0x.. [--amount N --payee P]  ask a human to approve; prints the link they sign at
  privi wait APPROVAL_ID                                     wait for the human's decision
  privi approvals [--status pending]                         your approval requests
  privi gateway create NAME UPSTREAM_URL [--min-score N] [--rate N] | list | stats ID | delete ID
  privi room open TITLE [--with ORG_ID] [--price X --payee P] | list | transcript ID | close ID | verify ID

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


# ---------------------------------------------------------------- Privi Live

def cmd_watch(a):
    import time
    key = "" if a.trust_only else api_key(False)
    q = f"channels={'org,trust' if key else 'trust'}&replay={a.replay}" + (f"&address={a.address}" if a.address else "")
    last = None
    print("privi: watching" + (" your organization + the trust network" if key else " the public trust network (delayed unless Pro)")
          + "; Ctrl-C to stop", file=sys.stderr)
    while True:
        req = urllib.request.Request(f"{base_url()}/live/events?{q}", headers={
            "Accept": "text/event-stream", "User-Agent": "privi-cli/1"})
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        if last:
            req.add_header("Last-Event-ID", last)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                name = data = None
                for raw in r:
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    if line.startswith("id:"):
                        last = line[3:].strip()
                    elif line.startswith("event:"):
                        name = line[6:].strip()
                    elif line.startswith("data:"):
                        data = line[5:].strip()
                    elif not line and data:
                        try:
                            ev = json.loads(data)
                            brief = " ".join(f"{k}={v}" for k, v in (ev.get("data") or {}).items()
                                             if k != "addresses" and not isinstance(v, (dict, list)))
                            print(f"{ev.get('at', '')[11:19]}  {name or ev.get('type'):<28} {brief[:200]}", flush=True)
                        except ValueError:
                            print(data, flush=True)
                        name = data = None
        except urllib.error.HTTPError as e:
            die(f"Ledger answered HTTP {e.code}: {e.read().decode()[:200]}")
        except (urllib.error.URLError, OSError):
            print("privi: connection lost, reconnecting…", file=sys.stderr)
            time.sleep(3)
        except KeyboardInterrupt:
            return


def cmd_kill(a):
    show(call("live_kill", {"stream_id": a.stream, "reason": a.reason or ""}))


def cmd_resume(a):
    show(call("live_resume", {"stream_id": a.stream}))


def cmd_ask(a):
    args = {"stream_id": a.stream, "action": a.action, "approver_wallet": a.approver, "ttl_s": a.ttl}
    if a.amount:
        args.update(amount_usdc=a.amount, payee=a.payee or "")
    if a.mandate:
        args["mandate_id"] = a.mandate
        args.pop("approver_wallet")
    r = call("approval_request", args)
    show(r, ["approval_id", "status", "approver", "expires_at", "approve_url"])
    print("\nSend the approver that link; then: privi wait " + r["approval_id"])


def cmd_wait(a):
    r = call("approval_wait", {"approval_id": a.approval_id, "timeout_s": 50}, auth=False)
    show(r, ["approval_id", "status", "decided_by", "decided_at", "use_until"])


def cmd_approvals(a):
    r = call("approval_list", {"status": a.status} if a.status else {})
    for x in r.get("approvals", []):
        print(f"{x['approval_id']}  {x['status']:<9} {x['stream_id']:<18} {x['action'][:70]}")
    if not r.get("approvals"):
        print("no approval requests")


def cmd_gateway(a):
    if a.op == "create":
        if not (a.name and a.arg):
            die("usage: privi gateway create NAME UPSTREAM_URL [--min-score N] [--rate N]")
        r = call("gateway_create", {"name": a.name, "upstream_url": a.arg, "min_score": a.min_score, "rate_per_min": a.rate})
        show(r, ["gw_id", "http_url", "ws_url", "upstream_host", "caller_gate", "rate_limit_per_minute_per_caller"])
    elif a.op == "list":
        for g in call("gateway_list")["gateways"]:
            st = g["stats"]
            print(f"{g['gw_id']}  {g['name']:<24} -> {g['upstream_host']:<28} calls={st['tool_calls']} errors={st['errors']}")
    elif a.op == "stats":
        if not a.name:
            die("usage: privi gateway stats GW_ID")
        r = call("gateway_stats", {"gw_id": a.name})
        show(r, ["gw_id", "name", "http_url", "ws_url", "stats", "quota"])
        for t in r["by_tool"]:
            print(f"  {t['tool']:<30} calls={t['calls']} errors={t['errors']} denied={t['denied']} payment_required={t['payment_required']}")
    elif a.op == "delete":
        if not a.name:
            die("usage: privi gateway delete GW_ID")
        show(call("gateway_delete", {"gw_id": a.name}))


def cmd_room(a):
    if a.op == "open":
        if not a.arg:
            die('usage: privi room open "TITLE" [--with ORG_ID] [--price 0.05 --payee seller.example.com]')
        args = {"title": a.arg}
        if a.with_org:
            args["counterparty_org_id"] = a.with_org
        if a.price:
            args.update(price_per_message_usdc=a.price, payee=a.payee or "")
        r = call("room_open", args)
        show(r, ["room_id", "ws_url", "join_code", "price_per_message_usdc", "expires_at"])
    elif a.op == "list":
        for r in call("room_list")["rooms"]:
            print(f"{r['room_id']}  {r['status']:<8} msgs={r['message_count']:<4} {r['title']}")
    elif a.op in ("transcript", "verify", "close"):
        if not a.arg:
            die(f"usage: privi room {a.op} ROOM_ID")
        if a.op == "close":
            show(call("room_close", {"room_id": a.arg}), ["room_id", "status", "message_count", "head_hash", "closed_at"])
            return
        t = call("room_transcript", {"room_id": a.arg})
        if a.op == "transcript":
            for m in t["messages"]:
                print(f"{m['seq']:>4}  {m['at'][11:19]}  {m['org_id'][:12]}  {m['body'][:120]}")
            print("chain:", json.dumps(t["verification"]))
        else:
            v = call("room_verify", {"room_id": a.arg, "messages": t["messages"]}, auth=False)
            show(v, ["room_id", "sealed", "seal_hash_ok", "signature_valid", "transcript", "anchor"])


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
    p = sp.add_parser("watch"); p.add_argument("--trust-only", action="store_true"); p.add_argument("--address")
    p.add_argument("--replay", type=int, default=10); p.set_defaults(f=cmd_watch)
    p = sp.add_parser("kill"); p.add_argument("stream", nargs="?", default="*"); p.add_argument("--reason"); p.set_defaults(f=cmd_kill)
    p = sp.add_parser("resume"); p.add_argument("stream", nargs="?", default="*"); p.set_defaults(f=cmd_resume)
    p = sp.add_parser("ask"); p.add_argument("action"); p.add_argument("--stream", default="cli")
    p.add_argument("--approver"); p.add_argument("--mandate"); p.add_argument("--amount"); p.add_argument("--payee")
    p.add_argument("--ttl", type=int, default=900); p.set_defaults(f=cmd_ask)
    p = sp.add_parser("wait"); p.add_argument("approval_id"); p.set_defaults(f=cmd_wait)
    p = sp.add_parser("approvals"); p.add_argument("--status"); p.set_defaults(f=cmd_approvals)
    p = sp.add_parser("gateway"); p.add_argument("op", choices=["create", "list", "stats", "delete"])
    p.add_argument("name", nargs="?"); p.add_argument("arg", nargs="?"); p.add_argument("--min-score", type=int, default=0)
    p.add_argument("--rate", type=int, default=60); p.set_defaults(f=cmd_gateway)
    p = sp.add_parser("room"); p.add_argument("op", choices=["open", "list", "transcript", "close", "verify"])
    p.add_argument("arg", nargs="?"); p.add_argument("--with", dest="with_org"); p.add_argument("--price"); p.add_argument("--payee")
    p.set_defaults(f=cmd_room)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
