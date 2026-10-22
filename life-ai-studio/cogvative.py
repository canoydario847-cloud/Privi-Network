"""Privi Cogvative Signature™ — line-level code attestations.

Copyright (c) 2026 Privi World Co. All rights reserved in this original module.
Neither a cryptographic signature nor this notice establishes ownership of
third-party code; licenses and contributor agreements govern authorship/rights.
"""
import difflib
import hashlib
import json
import os
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

BRAND = "Privi Cogvative Signature™"
NOTICE = "© 2026 Privi World Co. Privi Cogvative Signature™. Rights in underlying code are subject to applicable licenses and contributor agreements."
ROYALTY_BPS = 4000
CALL_CREDITS = 1
# Future mainnet price proposal, NOT an executed or escrowed PRVI payment.
PROPOSED_PRVI_PER_CALL_WEI = 10**18


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hexdigest(data):
    return hashlib.sha256(data).hexdigest()


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def signing_key():
    """32-byte Ed25519 seed MUST be supplied by operator, never generated per run."""
    value = os.getenv("PRIVI_COGVATIVE_ED25519_SEED", "").strip()
    if not value:
        return None
    if len(value) != 64:
        raise ValueError("Invalid Cogvative signing key length")
    try:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(value))
    except ValueError as exc:
        raise ValueError("Invalid Cogvative signing key") from exc


def attest(db, ident, owner_id, project_id, path, version, code, agent, source,
           run_id=None, credit_cost=None):
    """One immutable event per approved file version, with lineage for each line.

    Must be called inside the same SQL transaction that saves the code version.
    Unchanged lines retain the previous recorded attribution.
    """
    prior = db.execute(
        "SELECT id,event_hash,version FROM cog_events WHERE project_id=? AND path=? "
        "ORDER BY version DESC LIMIT 1", (project_id, path)).fetchone()
    if prior and prior["version"] >= version:
        raise ValueError("Out-of-order signature version")
    previous_lines = []
    if prior:
        previous_lines = [dict(r) for r in db.execute(
            "SELECT line_text,author_agent,author_time,origin_event FROM cog_lines "
            "WHERE event_id=? ORDER BY line_no", (prior["id"],))]
    lines = code.splitlines(keepends=True)
    previous_text = [item["line_text"] for item in previous_lines]
    mapping = {}
    for tag, p0, p1, n0, n1 in difflib.SequenceMatcher(
            a=previous_text, b=lines, autojunk=False).get_opcodes():
        if tag == "equal":
            for i, n in zip(range(p0, p1), range(n0, n1)):
                mapping[n] = previous_lines[i]

    stamped = timestamp()
    manifest_lines = []
    for n, line in enumerate(lines):
        inherited = mapping.get(n)
        manifest_lines.append({
            "line": n + 1, "code": line,
            "sha256": hexdigest(line.encode("utf-8")),
            "agent": inherited["author_agent"] if inherited else agent,
            "timestamp_utc": inherited["author_time"] if inherited else stamped,
            "origin_event": inherited["origin_event"] if inherited else ident,
        })
    payload = {
        "schema": "privi.cogvative.v1", "event_id": ident,
        "project": project_id, "path": path, "version": version,
        "actor": agent, "source": source, "run_id": run_id,
        "timestamp_utc": stamped, "content_sha256": hexdigest(code.encode("utf-8")),
        "prev_event_sha256": prior["event_hash"] if prior else None,
        "line_manifest_sha256": hexdigest(canonical(manifest_lines)),
        "line_count": len(lines), "credit_cost": credit_cost,
        "prvi_deployment_spent_wei": None, "gas_verification": "not_deployed",
        "rights_notice": NOTICE,
    }
    digest = hexdigest(canonical(payload))
    key = signing_key()
    signature = key.sign(bytes.fromhex(digest)).hex() if key else None
    pubkey = (key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
              if key else None)
    db.execute(
        "INSERT INTO cog_events "
        "(id,owner_id,project_id,path,version,agent,source,run_id,stamp_utc,content_sha256,"
        "prev_event_sha256,line_manifest_sha256,event_hash,signature_hex,pubkey_hex,"
        "credit_cost,prvi_deploy_wei,rights_notice,payload_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ident,owner_id,project_id,path,version,agent,source,run_id,stamped,
         payload["content_sha256"],payload["prev_event_sha256"],
         payload["line_manifest_sha256"],digest,signature,pubkey,credit_cost,
         None,NOTICE,canonical(payload).decode("utf-8")))
    db.executemany(
        "INSERT INTO cog_lines (event_id,line_no,line_text,line_sha256,author_agent,author_time,origin_event)"
        " VALUES (?,?,?,?,?,?,?)",
        [(ident, r["line"], r["code"], r["sha256"], r["agent"],
          r["timestamp_utc"], r["origin_event"]) for r in manifest_lines])
    return {"event_id": ident, "event_sha256": digest,
            "signature_status": "ed25519_signed" if signature else "hash_only_unsigned",
            "line_count": len(lines)}


def verify(event, lines):
    """Detect tampering, broken line manifest, and forged Ed25519 event signature."""
    payload = json.loads(event["payload_json"])
    manifest = [{
        "line": row["line_no"], "code": row["line_text"], "sha256": row["line_sha256"],
        "agent": row["author_agent"], "timestamp_utc": row["author_time"],
        "origin_event": row["origin_event"]
    } for row in lines]
    if any(x["sha256"] != hexdigest(x["code"].encode("utf-8")) for x in manifest):
        return False
    if payload["line_manifest_sha256"] != hexdigest(canonical(manifest)):
        return False
    if payload["content_sha256"] != hexdigest("".join(x["code"] for x in manifest).encode("utf-8")):
        return False
    if hexdigest(canonical(payload)) != event["event_hash"]:
        return False
    if not event["signature_hex"]:
        return None  # Hash integrity is checkable but cryptographic issuer not verified.
    if not event["pubkey_hex"]:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(event["pubkey_hex"])).verify(
            bytes.fromhex(event["signature_hex"]), bytes.fromhex(event["event_hash"]))
    except (ValueError, Exception):
        return False
    return True


def divide_royalties(lines, royalty_micros):
    """Deterministic per-line allocation; one caller charge, no double paying."""
    if not lines:
        return []
    counts = {}
    for line in lines:
        agent = line["author_agent"]
        counts[agent] = counts.get(agent, 0) + 1
    ordering = sorted(counts)
    denominator = len(lines)
    allocated = 0
    result = []
    for i, agent in enumerate(ordering):
        amount = (royalty_micros * counts[agent]) // denominator
        if i == len(ordering) - 1:
            amount = royalty_micros - allocated
        allocated += amount
        result.append((agent, counts[agent], amount))
    return result
