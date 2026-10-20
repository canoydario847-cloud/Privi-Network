#!/usr/bin/env python3
"""Privi-only IoT metadata database with local AI-assisted labels.

No cloud model, API key, token minting, PRVI transfers, or third-party chain.
Only confirmed event hashes and classification metadata are stored by default.
Values are non-binding *proposed* micro-PRVI estimates (1e-6 PRVI), not coins.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys

CATEGORIES = {
    "environment": (
        "temperature humidity air_quality co2 pm25 rainfall wind pressure weather sensor",
        "thermometer temperature dew_point ambient humid atmospheric climate",
        "water_quality ph conductivity turbidity environment weather station",
    ),
    "energy": (
        "voltage current watt watts kwh electricity consumption power meter",
        "battery charging solar inverter amp energy usage",
        "grid frequency load electric power outage",
    ),
    "industrial": (
        "motor vibration rpm machine bearing factory line pressure plc",
        "equipment maintenance vibration fault industrial machinery",
        "production assembly conveyor actuator flow sensor",
    ),
    "mobility": (
        "gps latitude longitude speed vehicle trip location odometer",
        "fleet route vehicle tracking transport mileage",
        "accelerometer brake fuel navigation motion car",
    ),
    "agriculture": (
        "soil moisture irrigation crop greenhouse fertilizer farm",
        "agriculture rainfall seed harvest nutrient field sensor",
        "plant soil sunlight irrigation pH greenhouse",
    ),
    "building": (
        "door lock occupancy room hvac thermostat lighting",
        "smart home access motion window alarm building",
        "room people occupancy lights ventilation heating",
    ),
    "health_device": (
        "heart_rate pulse oximeter spo2 wearable step_count",
        "medical sensor blood_pressure glucose patient health",
        "fitness heartbeat respiration wearable telemetry",
    ),
    "network": (
        "wifi rssi latency packet_loss uplink firmware cpu memory",
        "router gateway signal modem network disconnect",
        "iot heartbeat connected uptime ping battery_status",
    ),
    "other": (
        "iot device generic status telemetry measurement",
        "sensor observation value reading unknown",
    ),
}
TOKEN = re.compile(r"[a-z][a-z0-9_]{1,48}")
HEX32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
HEXT = re.compile(r"^0x[0-9a-fA-F]{40}$")


def tokens(text: str):
    return TOKEN.findall(text.lower())


def features(packet):
    """Only event names, field names and value types; no raw personal values."""
    if not isinstance(packet, dict) or not isinstance(packet.get("payload"), dict):
        raise ValueError("IoT payload must be an object")
    keys = []
    for key, value in packet["payload"].items():
        if not isinstance(key, str):
            raise ValueError("JSON field names required")
        keys.extend(tokens(key))
        if isinstance(value, dict):
            keys.extend(tokens(" ".join(str(k) for k in value.keys())))
    keys.extend(tokens(str(packet.get("eventType", ""))))
    return keys or ["sensor", "unknown"]


def predict(packet):
    """Small, offline multinomial Naive Bayes labeler; suggestions, not truth."""
    xs = features(packet)
    vocab = set()
    counts = {}
    totals = {}
    for category, samples in CATEGORIES.items():
        count = Counter()
        for sample in samples:
            count.update(tokens(sample))
        counts[category] = count
        totals[category] = sum(count.values())
        vocab.update(count)
    log_scores = {}
    for category in CATEGORIES:
        alpha = totals[category] + len(vocab)
        log_scores[category] = sum(
            math.log((counts[category][token] + 1) / alpha)
            for token in xs if token in vocab
        )
    largest = max(log_scores.values())
    probs = {k: math.exp(v - largest) for k, v in log_scores.items()}
    denominator = sum(probs.values())
    ordered = sorted(((k, v / denominator) for k, v in probs.items()),
                     key=lambda x: (-x[1], x[0]))
    category, confidence = ordered[0]
    return {
        "suggested_label": category,
        "confidence": round(confidence, 5),
        "review_required": confidence < 0.75,
        "alternatives": [{"label": k, "probability": round(v, 5)}
                         for k, v in ordered[:3]],
        "engine": "local-naive-bayes-v1",
    }


def quality_and_quote(packet):
    """Deterministic non-economic proposal: every eligible event > 0 units.

    Quotes are metadata, not ownership, a promise of payment, mint, or
    enforceable entitlement. AI labels do not control quote amounts.
    """
    payload = packet["payload"]
    if not isinstance(payload, dict) or len(payload) > 128:
        raise ValueError("Payload must contain at most 128 fields")
    score = 35 + min(len(payload), 10) * 3
    if len(str(packet.get("eventType", ""))) >= 3:
        score += 10
    observed = packet.get("observedAt", 0)
    if isinstance(observed, int) and not isinstance(observed, bool):
        delta = abs(int(datetime.now(timezone.utc).timestamp()) - observed)
        if delta <= 3600:
            score += 15
        elif delta <= 86400:
            score += 5
    score = max(1, min(score, 100))
    # Proposed micro-PRVI: 0.001000 + up to 0.002000 PRVI per accepted event.
    quote = 1000 + 20 * score
    return {"quality_score": score, "proposed_micro_prvi": quote,
            "proposed_prvi": f"{quote / 1_000_000:.6f}",
            "valuation_status": "PROPOSAL_ONLY_NOT_MINTED"}


def stable_json(value):
    if value is None or isinstance(value, (bool, str)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > (2**53 - 1):
            raise ValueError("Unsafe integer")
        return str(value)
    if isinstance(value, list):
        return "[" + ",".join(stable_json(x) for x in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise ValueError("Invalid field names")
        return "{" + ",".join(
            json.dumps(k, ensure_ascii=False, separators=(",", ":"))
            + ":" + stable_json(value[k]) for k in sorted(value)) + "}"
    raise ValueError("Floating point or unsupported payload value")


def sha(text):
    if isinstance(text, str):
        text = text.encode("utf-8")
    return "0x" + hashlib.sha256(text).hexdigest()


def event_hashes(packet):
    if packet.get("version") != 1:
        raise ValueError("Unexpected event version")
    device = packet.get("deviceId")
    kind = packet.get("eventType")
    seq = packet.get("sequence")
    ts = packet.get("observedAt")
    if not isinstance(device, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", device) is None:
        raise ValueError("Invalid device ID")
    if not isinstance(kind, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", kind) is None:
        raise ValueError("Invalid event type")
    if any(not isinstance(v, int) or isinstance(v, bool) or not (0 < v <= 2**53 - 1)
           for v in (seq, ts)):
        raise ValueError("Invalid sequence or timestamp")
    payload_text = stable_json(packet.get("payload"))
    if not isinstance(packet.get("payload"), dict) or len(payload_text.encode()) > 16384:
        raise ValueError("Invalid payload")
    payload_hash = sha(payload_text)
    signing_text = json.dumps([1, device, seq, ts, kind, payload_hash],
                              ensure_ascii=False, separators=(",", ":"))
    return {"deviceIdHash": sha(device), "payloadHash": payload_hash,
            "eventHash": sha(signing_text)}


DDL = """
CREATE TABLE IF NOT EXISTS iot_events(
    id INTEGER PRIMARY KEY,
    device_id_hash TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    event_hash TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    tx_hash TEXT NOT NULL UNIQUE,
    block_number INTEGER NOT NULL CHECK (block_number >= 0),
    evm_chain_id INTEGER NOT NULL CHECK (evm_chain_id > 0),
    label TEXT NOT NULL,
    confidence REAL NOT NULL,
    review_required INTEGER NOT NULL,
    alternatives_json TEXT NOT NULL,
    quality_score INTEGER NOT NULL CHECK (quality_score BETWEEN 1 AND 100),
    proposed_micro_prvi INTEGER NOT NULL CHECK (proposed_micro_prvi > 0),
    valuation_status TEXT NOT NULL CHECK (valuation_status = 'PROPOSAL_ONLY_NOT_MINTED'),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(device_id_hash, sequence)
);
"""


def record(db_path, packet, confirmation):
    if not isinstance(confirmation, dict):
        raise ValueError("Missing Privi confirmation")
    hashes = event_hashes(packet)
    for k in ("deviceIdHash", "payloadHash", "eventHash"):
        if confirmation.get(k, "").lower() != hashes[k].lower():
            raise ValueError("Confirmed event hash does not match packet: " + k)
    tx_hash = confirmation.get("transactionHash", "")
    chain_id = confirmation.get("chainId")
    block = confirmation.get("blockNumber")
    confirmations = confirmation.get("confirmations")
    if not HEX32.fullmatch(tx_hash) or not isinstance(chain_id, int) or isinstance(chain_id, bool) or chain_id <= 0:
        raise ValueError("Invalid confirmed Privi transaction identity")
    if not isinstance(block, int) or isinstance(block, bool) or block < 0:
        raise ValueError("Invalid confirmed block")
    if not isinstance(confirmations, int) or isinstance(confirmations, bool) or confirmations < 1:
        raise ValueError("Unconfirmed event")
    if chain_id in {1, 10, 56, 97, 137, 250, 42161, 43114, 8453, 84532, 11155111}:
        raise ValueError("Third-party EVM chain is not Privi")
    label = predict(packet)
    quote = quality_and_quote(packet)
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db, timeout=10) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(DDL)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO iot_events(
                device_id_hash,sequence,event_hash,payload_hash,tx_hash,
                block_number,evm_chain_id,label,confidence,review_required,
                alternatives_json,quality_score,proposed_micro_prvi,valuation_status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (hashes["deviceIdHash"], packet["sequence"], hashes["eventHash"],
             hashes["payloadHash"], tx_hash, block, chain_id, label["suggested_label"],
             label["confidence"], int(label["review_required"]),
             json.dumps(label["alternatives"]), quote["quality_score"],
             quote["proposed_micro_prvi"], quote["valuation_status"])
        )
    return {"deviceIdHash": hashes["deviceIdHash"], "eventHash": hashes["eventHash"],
            "transactionHash": tx_hash, **label, **quote,
            "stored_raw_sensor_data": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["label", "record"])
    p.add_argument("--db", type=Path, help="SQLite database path (record only)")
    p.add_argument("--packet", type=Path, help="JSON packet for offline labeling")
    args = p.parse_args()
    try:
        if args.command == "label":
            if args.packet is None:
                raise ValueError("--packet is required for labeling")
            packet = json.loads(args.packet.read_text(encoding="utf-8"))
            result = {**predict(packet), **quality_and_quote(packet)}
        else:
            if args.db is None:
                raise ValueError("--db is required for recording")
            # Only a trusted local gateway must call this mode, after Privi
            # RPC verification and a successful on-chain receipt.
            incoming = json.load(sys.stdin)
            result = record(args.db, incoming["packet"], incoming["confirmation"])
        print(json.dumps(result, indent=2))
    except (ValueError, KeyError, sqlite3.Error, json.JSONDecodeError) as e:
        print("Privi IoT operation rejected: " + str(e), file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
