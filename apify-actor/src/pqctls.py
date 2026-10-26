# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Check whether a public TLS endpoint already uses post-quantum (hybrid ML-KEM) key exchange.

Two raw TLS ClientHello probes, no handshake is completed and no application data is sent:

1. Post-quantum probe: offers ONLY a hybrid ML-KEM group (X25519MLKEM768, then SecP256r1MLKEM768)
   with an empty key share. A server that supports the group must answer with a HelloRetryRequest
   that selects it; a server that doesn't answers with a handshake_failure alert.
2. Classical probe: offers x25519/P-256 plus TLS 1.3 and TLS 1.2 cipher suites, to learn the
   highest TLS version the server negotiates.

Only public (globally routable) addresses on a short list of TLS ports are probed.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

HRR_RANDOM = bytes.fromhex("cf21ad74e59a6111be1d8c021e65b891c2a211167abb8c5e079e09e2c8a8339c")
PQ_GROUPS = {0x11EC: "X25519MLKEM768", 0x11EB: "SecP256r1MLKEM768"}
CLASSICAL_GROUPS = {0x001D: "X25519", 0x0017: "secp256r1"}
TLS13_SUITES = [0x1301, 0x1302, 0x1303]
TLS12_SUITES = [0xC02F, 0xC030, 0xC02B, 0xC02C, 0xCCA8, 0xCCA9, 0x009C, 0x009D]
SIG_ALGS = [0x0403, 0x0804, 0x0401, 0x0503, 0x0805, 0x0501, 0x0806, 0x0601, 0x0807, 0x0201]
ALLOWED_PORTS = {443, 8443, 4443, 465, 636, 853, 993, 995}
MAX_HOSTS = 20
HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
ALERTS = {40: "handshake_failure", 47: "illegal_parameter", 50: "decode_error", 70: "protocol_version",
          71: "insufficient_security", 80: "internal_error", 109: "missing_extension", 112: "unrecognized_name"}


class ProbeError(Exception):
    pass


def _vec(data: bytes, n: int) -> bytes:
    return len(data).to_bytes(n, "big") + data


def _ext(etype: int, body: bytes) -> bytes:
    return struct.pack(">HH", etype, len(body)) + body


def client_hello(host: str, groups: list[int], key_shares: list[tuple[int, bytes]], suites: list[int]) -> bytes:
    exts = b""
    if not _is_ip(host):
        name = host.encode("idna")
        exts += _ext(0x0000, _vec(b"\x00" + _vec(name, 2), 2))
    exts += _ext(0x002B, _vec(b"\x03\x04\x03\x03", 1))                     # supported_versions: 1.3, 1.2
    exts += _ext(0x000A, _vec(b"".join(struct.pack(">H", g) for g in groups), 2))
    exts += _ext(0x000B, b"\x01\x00")                                      # ec_point_formats: uncompressed
    exts += _ext(0x000D, _vec(b"".join(struct.pack(">H", s) for s in SIG_ALGS), 2))
    exts += _ext(0x0033, _vec(b"".join(struct.pack(">H", g) + _vec(k, 2) for g, k in key_shares), 2))
    exts += _ext(0x002D, b"\x01\x01")                                      # psk_key_exchange_modes: psk_dhe_ke
    body = (b"\x03\x03" + os.urandom(32) + _vec(os.urandom(32), 1)
            + _vec(b"".join(struct.pack(">H", s) for s in suites), 2) + b"\x01\x00" + _vec(exts, 2))
    hs = b"\x01" + len(body).to_bytes(3, "big") + body
    return b"\x16\x03\x01" + _vec(hs, 2)


def parse_server_reply(data: bytes) -> dict[str, Any]:
    """Parse the first TLS records from a server: an alert or the (Retry)ServerHello."""
    hs = b""
    i = 0
    while i + 5 <= len(data):
        rtype, _, rlen = data[i], data[i + 1:i + 3], int.from_bytes(data[i + 3:i + 5], "big")
        rec = data[i + 5:i + 5 + rlen]
        if len(rec) < rlen:
            break
        i += 5 + rlen
        if rtype == 21 and len(rec) >= 2:
            return {"kind": "alert", "alert": ALERTS.get(rec[1], f"alert {rec[1]}")}
        if rtype == 22:
            hs += rec
            if len(hs) >= 4 and len(hs) >= 4 + int.from_bytes(hs[1:4], "big"):
                break
    if len(hs) < 4 or hs[0] != 2:
        raise ProbeError("no ServerHello in reply")
    body = hs[4:4 + int.from_bytes(hs[1:4], "big")]
    p = 2
    random = body[p:p + 32]; p += 32
    p += 1 + body[p]
    suite = int.from_bytes(body[p:p + 2], "big"); p += 3
    out: dict[str, Any] = {"kind": "hrr" if random == HRR_RANDOM else "server_hello", "cipher_suite": suite,
                           "version": "1.2" if body[:2] == b"\x03\x03" else "older", "group": None}
    if p + 2 <= len(body):
        end = p + 2 + int.from_bytes(body[p:p + 2], "big"); p += 2
        while p + 4 <= end:
            et, el = struct.unpack(">HH", body[p:p + 4]); ev = body[p + 4:p + 4 + el]; p += 4 + el
            if et == 0x002B and len(ev) == 2:
                out["version"] = {b"\x03\x04": "1.3", b"\x03\x03": "1.2"}.get(ev, "unknown")
            elif et == 0x0033 and len(ev) >= 2:
                out["group"] = int.from_bytes(ev[:2], "big")
    return out


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def resolve_public(host: str, port: int) -> str:
    """Resolve host and refuse anything that is not a globally routable address."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as ex:
        raise ProbeError(f"DNS lookup failed: {ex.strerror}") from None
    addrs = [i[4][0] for i in infos]
    if not addrs:
        raise ProbeError("no addresses")
    for a in addrs:
        if not ipaddress.ip_address(a.split("%")[0]).is_global:
            raise ProbeError("resolves to a private or reserved address; only public endpoints are checked")
    return addrs[0]


def _exchange(ip: str, port: int, hello: bytes, timeout: float) -> dict[str, Any]:
    with socket.create_connection((ip, port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(hello)
        buf = b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and len(buf) < 65536:
            try:
                chunk = s.recv(16384)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            try:
                return parse_server_reply(buf)
            except (ProbeError, IndexError):
                continue
        if not buf:
            raise ProbeError("connection closed without a reply")
        return parse_server_reply(buf)


def normalize(target: str, default_port: int = 443) -> tuple[str, int]:
    t = target.strip().lower()
    t = re.sub(r"^[a-z][a-z0-9+.-]*://", "", t).split("/")[0].split("?")[0]
    port = default_port
    if t.startswith("["):
        host, _, rest = t[1:].partition("]")
        if rest.startswith(":"):
            port = int(rest[1:])
    elif t.count(":") == 1:
        host, p = t.split(":")
        port = int(p)
    else:
        host = t
    host = host.rstrip(".")
    if not (_is_ip(host) or HOST_RE.match(host)):
        raise ProbeError("not a valid hostname")
    if port not in ALLOWED_PORTS:
        raise ProbeError(f"port {port} is not checked; allowed TLS ports: {sorted(ALLOWED_PORTS)}")
    return host, port


def check_endpoint(target: str, timeout: float = 5.0, resolver=resolve_public) -> dict[str, Any]:
    """Probe one endpoint. Never raises; the result carries status 'invalid' or 'unreachable' instead."""
    try:
        host, port = normalize(target)
    except (ProbeError, ValueError) as ex:
        return {"target": target, "status": "invalid", "detail": str(ex)}
    res: dict[str, Any] = {"target": target, "host": host, "port": port}
    try:
        ip = resolver(host, port)
    except ProbeError as ex:
        return {**res, "status": "blocked" if "private" in str(ex) else "unreachable", "detail": str(ex)}
    res["ip"] = ip

    pq_group, pq_note = None, None
    for g, name in PQ_GROUPS.items():
        try:
            r = _exchange(ip, port, client_hello(host, [g], [], TLS13_SUITES), timeout)
        except (OSError, ProbeError) as ex:
            pq_note = f"post-quantum probe: {ex}"
            continue
        if r["kind"] == "hrr" and r["group"] == g:
            pq_group = name
            break
        pq_note = f"{name} not accepted ({r.get('alert') or r['kind']})"

    try:
        c = _exchange(ip, port, client_hello(host, list(CLASSICAL_GROUPS), [(0x001D, os.urandom(32))],
                                             TLS13_SUITES + TLS12_SUITES), timeout)
        version = c.get("version") if c["kind"] != "alert" else None
        classical_group = CLASSICAL_GROUPS.get(c.get("group") or 0)
    except (OSError, ProbeError) as ex:
        if pq_group is None:
            return {**res, "status": "unreachable", "detail": f"no TLS reply: {ex}"}
        version, classical_group = "1.3", None
    if pq_group:
        version = "1.3"

    if pq_group:
        status, action = "pq_hybrid", "Hybrid post-quantum key exchange is on. Keep it as the preferred group; plan ML-DSA certificates when CAs issue them."
    elif version == "1.3":
        status, action = "tls13_classical", "TLS 1.3 is on but key exchange is classical. Enable the X25519MLKEM768 group (OpenSSL 3.5+, BoringSSL, Go 1.24+, recent load balancers)."
    elif version == "1.2":
        status, action = "tls12", "Upgrade to TLS 1.3 (OMB M-26-15 deadline Jan 2, 2030) and enable X25519MLKEM768."
    else:
        status, action = "no_tls13", "The server did not negotiate TLS 1.2 or 1.3 with modern suites. Upgrade TLS, then enable X25519MLKEM768."
    algorithm = pq_group or (classical_group and f"ECDHE {classical_group}") or ("ECDHE" if version else "unknown")
    return {**res, "status": status, "tls_version": version, "pq_key_exchange": pq_group,
            "classical_key_exchange": classical_group, "detail": pq_note if not pq_group else None, "action": action,
            "asset": {"system": host, "asset": f"{host}:{port} TLS key exchange", "algorithm": algorithm,
                      "usage": "tls", "protocol": f"TLS {version}" if version else "", "source": "Privi Quantum endpoint check"}}


def check_endpoints(targets: list[str], timeout: float = 5.0, resolver=resolve_public) -> dict[str, Any]:
    targets = [t for t in dict.fromkeys(str(t).strip() for t in targets) if t][:MAX_HOSTS]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda t: check_endpoint(t, timeout, resolver), targets))
    checked = [r for r in results if r["status"] in ("pq_hybrid", "tls13_classical", "tls12", "no_tls13")]
    pq = sum(r["status"] == "pq_hybrid" for r in checked)
    return {
        "summary": {"checked": len(checked), "pq_hybrid": pq,
                    "tls13_classical": sum(r["status"] == "tls13_classical" for r in checked),
                    "below_tls13": sum(r["status"] in ("tls12", "no_tls13") for r in checked),
                    "unreachable_or_invalid": len(results) - len(checked),
                    "pq_ready_percent": round(100 * pq / len(checked)) if checked else None},
        "results": results,
        "note": ("Checks the key exchange a server negotiates (what protects recorded traffic from later quantum "
                 "decryption). Certificate signatures stay classical until certificate authorities issue ML-DSA "
                 "certificates. Pass each result's 'asset' to pqc_readiness_package to add it to the CBOM."),
    }
