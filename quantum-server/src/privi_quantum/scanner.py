# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Quantum-vulnerability scanner.

Walks a codebase or config tree and flags cryptography that a large quantum
computer breaks (Shor: RSA, ECC, DH, DSA) or weakens (Grover: 128-bit
symmetric keys), plus algorithms already broken classically. Produces a
readiness score and a migration recommendation per finding.

Pattern matching is heuristic: it finds where to look, it doesn't prove
absence. Treat a clean scan as "nothing obvious," not "quantum-safe."
"""
import json
import os
import re
from dataclasses import dataclass, asdict

CRITICAL, HIGH, MEDIUM, INFO = "CRITICAL", "HIGH", "MEDIUM", "INFO"
WEIGHT = {CRITICAL: 10, HIGH: 6, MEDIUM: 2, INFO: 0}

SHOR = "Broken by Shor's algorithm on a large quantum computer"
GROVER = "Security roughly halved by Grover's algorithm"
CLASSIC = "Already broken by classical attacks"

# (id, severity, regex, why, fix)
RULES = [
    ("rsa-pem", CRITICAL, r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
     SHOR + "; private key committed to source", "Remove the key from the repo, rotate it, and reissue with ML-DSA / ML-KEM"),
    ("ssh", HIGH, r"\bssh-rsa\b|\becdsa-sha2-nistp\d+\b|\bssh-ed25519\b",
     SHOR, "Enable a PQ hybrid SSH key exchange (e.g. mlkem768x25519-sha256 / sntrup761x25519) and plan PQ host keys"),
    ("jwt-asym", HIGH, r"[\"'](?:RS|PS|ES)(?:256|384|512)[\"']",
     SHOR, "JWT signing with RSA/ECDSA; plan migration to ML-DSA-based JWS once your stack supports it"),
    ("ecdh", HIGH, r"\bECDHE?\b|\bX25519\b|\bX448\b|\bexchange\(\s*ec\.ECDH",
     SHOR, "Use hybrid X25519+ML-KEM-768 key exchange"),
    ("ecdsa", HIGH, r"\bECDSA\b|ec\.generate_private_key|ecdsa\.|SigningKey\.generate|\bES(?:256|384|512)K?\b",
     SHOR, "Migrate signatures to ML-DSA-65 or hybrid Ed25519+ML-DSA-65"),
    ("curve", HIGH, r"\bsecp256k1\b|\bsecp256r1\b|\bprime256v1\b|\bP-?256\b|\bP-?384\b|\bSECP\d+R1\b",
     SHOR, "Elliptic-curve keys need a post-quantum replacement (ML-DSA / ML-KEM)"),
    ("eddsa", HIGH, r"\bEd25519\b|\bEd448\b|\bEdDSA\b",
     SHOR, "Pair with ML-DSA-65 (hybrid) or replace with ML-DSA"),
    ("dh", HIGH, r"\bDiffie[- ]?Hellman\b|\bDHE?_|\bdh\.generate_parameters|\bDH_generate",
     SHOR, "Replace finite-field DH with ML-KEM-768"),
    ("dsa", HIGH, r"\bDSA\b|dsa\.generate_private_key",
     SHOR, "Replace DSA with ML-DSA-65"),
    ("rsa", HIGH,
     r"\bRSA(?:_|-)?(?:1024|2048|3072|4096)?\b|rsa\.generate|generate_private_key\(\s*public_exponent|RSA_generate_key|KeyPairGenerator\.getInstance\(\"RSA\"",
     SHOR, "Replace RSA key exchange with ML-KEM-768 and RSA signatures with ML-DSA-65 (hybrid during migration)"),
    ("aes128", MEDIUM, r"\bAES[-_]?128\b|aes-128-|\bAES128\b",
     GROVER, "Move to AES-256 for long-lived secrets"),
    ("sha1", MEDIUM, r"\bSHA-?1\b|hashlib\.sha1|\bsha1\(",
     CLASSIC, "Use SHA-256, SHA-384 or SHA3-256"),
    ("md5", MEDIUM, r"\bMD5\b|hashlib\.md5|\bmd5\(",
     CLASSIC, "Use SHA-256 or SHA3-256"),
    ("3des", MEDIUM, r"\b3DES\b|\bTripleDES\b|\bDES-EDE3\b|\bDESede\b",
     CLASSIC + " and quantum-weakened", "Use AES-256-GCM"),
    ("pqc-present", INFO, r"\bML[-_]?KEM\b|\bKyber\b|\bML[-_]?DSA\b|\bDilithium\b|\bSLH[-_]?DSA\b|\bSPHINCS\+?\b|\bFalcon\b|mlkem768",
     "Post-quantum algorithm in use", "Good - confirm it's deployed in hybrid mode where classical crypto remains"),
]
_COMPILED = [(i, s, re.compile(p, re.IGNORECASE if i not in ("dsa",) else 0), w, f)
             for i, s, p, w, f in RULES]

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
             "build", "_vendor", ".tox", ".mypy_cache", "target"}
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt",
            ".c", ".h", ".cpp", ".cc", ".cs", ".rb", ".php", ".swift", ".sol",
            ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env",
            ".pem", ".key", ".crt", ".tf", ".sh", ".md", ".txt", ".xml", ""}
MAX_BYTES = 2_000_000


@dataclass
class Finding:
    rule: str
    severity: str
    path: str
    line: int
    snippet: str
    why: str
    fix: str


def _iter_files(root: str):
    if os.path.isfile(root):
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in TEXT_EXT or name in ("Dockerfile", "sshd_config", "ssh_config"):
                yield os.path.join(dirpath, name)


def _scan_lines(lines, label: str) -> list[Finding]:
    file_hits = []
    for n, text in enumerate(lines, 1):
        seen_sev = set()  # rules are ordered specific-first; one hit per severity per line
        for rid, sev, rx, why, fix in _COMPILED:
            if sev not in seen_sev and rx.search(text):
                seen_sev.add(sev)
                file_hits.append(Finding(rid, sev, label, n, text.strip()[:160], why, fix))
    # If the same file already uses a post-quantum algorithm, classical
    # findings there are likely the classical half of a hybrid.
    if any(h.rule == "pqc-present" for h in file_hits):
        for h in file_hits:
            if h.severity == HIGH:
                h.severity = INFO
                h.why += " (paired with post-quantum crypto in this file - likely hybrid)"
    return file_hits


def scan_text(text: str, filename: str = "input") -> dict:
    """Scan one pasted file or config (used by the MCP tool; nothing touches disk)."""
    return _report(_scan_lines(text.splitlines(), filename[:200]), 1, filename[:200])


def scan(root: str) -> dict:
    findings: list[Finding] = []
    files = 0
    for path in _iter_files(root):
        try:
            if os.path.getsize(path) > MAX_BYTES:
                continue
            with open(path, "r", encoding="utf-8", errors="strict") as f:
                lines = f.readlines()
        except (UnicodeDecodeError, OSError):
            continue
        files += 1
        findings.extend(_scan_lines(lines, os.path.relpath(path, root) if os.path.isdir(root) else path))
    return _report(findings, files, os.path.abspath(root))


def _report(findings: list[Finding], files: int, root: str) -> dict:
    counts = {s: sum(1 for f in findings if f.severity == s) for s in WEIGHT}
    penalty = sum(WEIGHT[f.severity] for f in findings)
    score = max(0, round(100 - penalty * 100 / (penalty + 40))) if penalty else 100
    order = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, INFO: 3}
    findings.sort(key=lambda f: (order[f.severity], f.path, f.line))
    return {
        "generated_by": "Privi Quantum (Privi Quantum Trust Layer scanner)",
        "copyright": "Copyright (c) 2026 Privi World Co. All rights reserved.",
        "root": root,
        "files_scanned": files,
        "readiness_score": score,
        "counts": counts,
        "findings": [asdict(f) for f in findings],
    }


def format_report(report: dict, show_info: bool = False) -> str:
    c = report["counts"]
    out = [
        "Privi Quantum Trust Layer - Quantum Readiness Report",
        "Copyright (c) 2026 Privi World Co. All rights reserved.",
        "",
        f"Quantum readiness scan: {report['root']}",
        f"Files scanned: {report['files_scanned']}",
        f"Readiness score: {report['readiness_score']}/100",
        f"Critical {c['CRITICAL']}  High {c['HIGH']}  Medium {c['MEDIUM']}  Info {c['INFO']}",
        "",
    ]
    for f in report["findings"]:
        if f["severity"] == INFO and not show_info:
            continue
        out.append(f"[{f['severity']}] {f['path']}:{f['line']}  ({f['rule']})")
        out.append(f"    {f['snippet']}")
        out.append(f"    why: {f['why']}")
        out.append(f"    fix: {f['fix']}")
    if not any(f["severity"] != INFO for f in report["findings"]):
        out.append("No quantum-vulnerable patterns found (heuristic scan).")
    return "\n".join(out)


def to_json(report: dict) -> str:
    return json.dumps(report, indent=2)
