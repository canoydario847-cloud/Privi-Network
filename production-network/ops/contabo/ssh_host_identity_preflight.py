#!/usr/bin/env python3
"""Verify a Contabo VPS SSH host key against an OUT-OF-BAND trusted fingerprint.

The expected Ed25519 fingerprint MUST first be read from the authenticated
Contabo VNC/rescue console, never from ssh-keyscan itself or untrusted email.
Makes ONE unauthenticated ssh-keyscan network call; NEVER logs in, writes
known_hosts, accesses keys/passwords, changes firewalls, creates nodes or coins.

This is a staging connection identity preflight, not proof of OS security,
payment, host ownership, fault isolation, or financial mainnet authorization.
"""
import argparse
import base64
import binascii
import hashlib
import ipaddress
import re
import shutil
import subprocess
import sys

FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
ED25519 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


def public_ipv4(address):
    if not isinstance(address, str):
        raise ValueError("expected one public IPv4 address")
    try:
        host = ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError as exc:
        raise ValueError("expected one public IPv4 address") from exc
    if not host.is_global:
        raise ValueError("refusing non-public IPv4 address")
    return str(host)


def _verify_keyscan_output(output, host, port, expected):
    """Pure parser: no network or subprocess. Public key/fingerprint not logged."""
    if not isinstance(output, str) or len(output) > 16_384:
        raise ValueError("SSH keyscan response malformed or oversized")
    canonical_host = host if port == 22 else f"[{host}]:{port}"
    keys = set()
    for raw in output.splitlines():
        if not raw or raw.startswith("#"):
            continue
        fields = raw.split()
        if len(fields) != 3 or fields[0] != canonical_host or fields[1] != "ssh-ed25519":
            raise ValueError("unexpected SSH host-key record")
        encoded = fields[2]
        if not ED25519.fullmatch(encoded):
            raise ValueError("invalid SSH host public-key format")
        try:
            blob = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid SSH host public-key encoding") from exc
        if len(blob) != 51 or blob[:19] != b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20":
            raise ValueError("invalid SSH Ed25519 public-key blob")
        keys.add(blob)
    if len(keys) != 1:
        raise ValueError("expected exactly one distinct SSH Ed25519 host key")
    key = next(iter(keys))
    actual = base64.b64encode(hashlib.sha256(key).digest()).decode("ascii").rstrip("=")
    if ("SHA256:" + actual) != expected:
        raise ValueError("server SSH identity DOES NOT match trusted console fingerprint")
    return {
        "ssh_host_identity": "MATCHED_OUT_OF_BAND_ED25519_FINGERPRINT",
        "port": port,
        "remote_shell": "NOT_ATTEMPTED",
        "host_changed": False,
        "financial_mainnet": "NOT_ACTIVE",
    }


def preflight(host, expected_fingerprint, port=22, timeout=5):
    host = public_ipv4(host)
    if not isinstance(expected_fingerprint, str) or not FINGERPRINT.fullmatch(expected_fingerprint):
        raise ValueError("a verified SHA256: Ed25519 fingerprint from trusted Contabo VNC is required")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("SSH port must be in 1..65535")
    if type(timeout) is not int or not 1 <= timeout <= 10:
        raise ValueError("SSH scan timeout must be in 1..10 seconds")
    program = shutil.which("ssh-keyscan")
    if not program:
        raise ValueError("OpenSSH ssh-keyscan utility is not installed")
    try:
        result = subprocess.run(
            [program, "-T", str(timeout), "-p", str(port), "-t", "ed25519", host],
            capture_output=True, text=True, timeout=timeout + 4, check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise ValueError("SSH host-key scan unavailable; check provider console/firewall") from exc
    # ssh-keyscan stderr can contain unsolicited remote banners: do not log it.
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError("SSH host-key scan unavailable; port 22 may be blocked/refused")
    return _verify_keyscan_output(result.stdout, host, port, expected_fingerprint)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host-ipv4", required=True)
    ap.add_argument("--trusted-ed25519-sha256", required=True,
                    help="SHA256:... fingerprint from authenticated Contabo VNC (not keyscan)")
    ap.add_argument("--port", type=int, default=22)
    ns = ap.parse_args()
    try:
        result = preflight(ns.host_ipv4, ns.trusted_ed25519_sha256, ns.port)
    except ValueError as exc:
        # No remote banners, private keys or arbitrary public IP in error output.
        print("SSH IDENTITY NO-GO:", str(exc), file=sys.stderr)
        return 2
    import json
    print(json.dumps(result, sort_keys=True))
    print("Identity check only: still verify server OS, access controls, RPC binding and authorized staging use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
