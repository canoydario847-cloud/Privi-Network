"""Privi Guard engine: decide whether text is safe for an AI agent to act on (inbound) or to send (outbound).

Pure functions, no I/O, no storage. Privi never keeps the text it inspects; only its SHA-256.

inbound   untrusted content entering the agent (web pages, emails, documents, tool results, other agents'
          messages): prompt injection, role spoofing, tool coercion, exfiltration instructions, hidden text.
outbound  what the agent is about to send, post, write or pass to a tool: credentials, private keys, card
          numbers, government IDs, and data smuggled out through URLs.
"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Iterable

ENGINE_VERSION = "guard-1.0"
MAX_CHARS = 400_000
UNIT_CHARS = 100_000          # one billable check covers up to this many characters
WEIGHT = {"high": 60, "medium": 25, "low": 8, "info": 0}

I = re.IGNORECASE
IM = re.IGNORECASE | re.MULTILINE

# ---------------------------------------------------------------- inbound rules

INBOUND: list[tuple[str, str, str, re.Pattern]] = [
    ("high", "instruction_override", "tries to replace the agent's instructions",
     re.compile(r"\b(ignore|disregard|forget|override|bypass)\s+(all\s+|any\s+|the\s+|your\s+|every\s+)*(previous|prior|above|earlier|preceding|"
                r"original|system|existing|current)\s+(instructions?|prompts?|rules|directions|guidelines|context|messages)", I)),
    ("high", "role_spoofing", "contains chat-template or fake system turns that impersonate the operator",
     re.compile(r"<\|(im_start|im_end|system|assistant|user|endoftext|eot_id|start_header_id)\|>|\[/?INST\]|<<\s*/?SYS\s*>>"
                r"|^[ \t]*#{2,}[ \t]*(system|instruction)s?[ \t]*(prompt)?[ \t]*:?[ \t]*$"
                r"|^[ \t]*(system|assistant)[ \t]*:\s*(you|ignore|from\s+now|new\s+instructions?|always|never|do\s+not|important)\b"
                r"|\b(begin|start)\s+(of\s+)?(new\s+)?system\s+(prompt|message|instructions?)\b"
                r"|\byou\s+are\s+now\s+(in\s+)?(developer|admin|dan|god|jailbreak|unrestricted|debug)\s+mode\b"
                r"|\bnew\s+(system\s+)?instructions?\s*:", IM)),
    ("high", "exfiltration_instruction", "asks the agent to send private data somewhere",
     re.compile(r"\b(send|email|post|forward|upload|transmit|leak|exfiltrate|paste|submit|append)\b[^.\n]{0,60}\b(conversation|chat\s+history|"
                r"system\s+prompt|api[\s_-]?keys?|passwords?|credentials?|secrets?|tokens?|private\s+keys?|seed\s+phrase|"
                r"cookies?|session|ssh\s+keys?|\.env|environment\s+variables|user'?s?\s+(data|files|emails?|details))\b"
                r"[^.\n]{0,60}\b(to|at|into|via)\s+(https?://|\S+@\S+\.\w+|this\s+(url|address|endpoint|webhook)|the\s+following)", I)),
    ("high", "prompt_leak_request", "asks the agent to reveal its hidden instructions",
     re.compile(r"\b(reveal|print|output|repeat|show|display|tell\s+me|give\s+me)\s+(me\s+)?(your|the)\s+(full\s+|entire\s+|exact\s+|original\s+)?"
                r"(system\s+prompt|hidden\s+instructions|initial\s+instructions|developer\s+(message|instructions))", I)),
    ("high", "concealment", "tells the agent to hide what it is doing from the user",
     re.compile(r"\b(do\s+not|don'?t|never)\s+(tell|inform|mention\s+(this\s+)?to|notify|alert|let)\s+the\s+user\s+(about\s+|know\s+)?"
                r"(this|these|that\s+you|what\s+you|the\s+(instruction|step|request|action))"
                r"|\bwithout\s+(telling|informing|notifying|alerting)\s+the\s+user\b"
                r"|\b(secretly|silently|covertly)\s+(send|call|run|execute|forward|transfer|email|delete)\b", I)),
    ("medium", "tool_coercion", "tries to make the agent call tools or take actions",
     re.compile(r"\b(you\s+must|you\s+should|immediately|now)\s+(call|use|run|invoke|execute)\s+(the\s+)?[\w.-]+\s+(tool|function|command)\b"
                r"|\b(call|use|invoke)\s+the\s+[\w.-]+\s+tool\s+(with|to)\s+(send|transfer|pay|delete|email|forward)", I)),
    ("medium", "payment_coercion", "pushes the agent to move money or approve a payment",
     re.compile(r"\b(transfer|send|wire|pay|approve)\s+[^.\n]{0,40}(\$\s?\d|\d+(\.\d+)?\s?(usd|usdc|eth|btc|dollars))[^.\n]{0,60}\b(to|into)\s+"
                r"(wallet|address|account|0x[0-9a-f]{6,}|iban)", I)),
]
DESCRIBES = re.compile(r"\b(detects?|detecting|detection|finds?|flags?|checks?\s+(for|whether|if)|scans?|scanning|identif\w*|"
                       r"look(s|ing)?\s+for|such\s+as|e\.g\.|for\s+example|examples?\s+of|patterns?\s+(like|such)|attacks?\s+(like|such)|"
                       r"called|known\s+as|injection|jailbreaks?|researchers?|attackers?\s+(can|could|may|might|use))\b", I)
HIDDEN_CHARS = re.compile("[​-‏⁠-⁤‪-‮⁦-⁩﻿\U000e0000-\U000e007f]")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
HIDDEN_HTML = re.compile(r"<[^<>]{0,300}?style\s*=\s*[\"'][^\"'<>]{0,300}?(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0(?![.\d]*[1-9]))"
, I)
COMMENT_WORDS = re.compile(r"instruction|assistant|ignore|system\s+prompt|you\s+must", I)


def _hidden_comment(text: str):
    """Linear scan of HTML comments for instructions (no regex backtracking on unclosed '<!--')."""
    i = 0
    while True:
        a = text.find("<!--", i)
        if a < 0:
            return None
        b = text.find("-->", a + 4, a + 4004)
        body = text[a + 4:b if b >= 0 else a + 4004]
        if COMMENT_WORDS.search(body):
            return a, (b + 3 if b >= 0 else a + 4 + len(body))
        i = (b + 3) if b >= 0 else a + 4004      # never rescan the same window
MD_IMAGE = re.compile(r"!\[[^\]\n]{0,300}\]\(\s*(https?://[^)\s]{1,3000})", I)
PLACEHOLDER = re.compile(r"\{|\$|%7B|<|\[", I)
LONG_B64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{80,}={0,2}(?![A-Za-z0-9+/=])")

# ---------------------------------------------------------------- outbound rules

SECRETS: list[tuple[str, str, re.Pattern]] = [
    ("private_key", "a PEM private key", re.compile(r"-----BEGIN ((RSA|EC|DSA|OPENSSH|ENCRYPTED|PGP) )?PRIVATE KEY( BLOCK)?-----")),
    ("aws_access_key", "an AWS access key ID", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", "a GitHub token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{60,}\b")),
    ("anthropic_key", "an Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{30,}")),
    ("openai_key", "an OpenAI API key", re.compile(r"\bsk-(proj-|svcacct-|admin-)?[A-Za-z0-9_-]{32,}")),
    ("stripe_live_key", "a live Stripe secret key", re.compile(r"\b(sk|rk)_live_[A-Za-z0-9]{20,}")),
    ("slack_token", "a Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", "a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", "a signed JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("eth_private_key", "an Ethereum private key", re.compile(r"(private[\s_-]?key|privkey|secret)[\"'\s:=]{1,6}(0x)?[0-9a-fA-F]{64}\b", I)),
    ("password_assignment", "a password in plain text", re.compile(r"\b(password|passwd|pwd)\s*[:=]\s*[\"']?[^\s\"']{6,}", I)),
    ("seed_phrase", "a wallet seed phrase", re.compile(r"(seed\s+phrase|mnemonic|recovery\s+phrase)\s*[:=\-]?\s*[\"']?((?:[a-z]{3,8}\s+){11,23}[a-z]{3,8})\b", I)),
]
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
SSN = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
URL = re.compile(r"https?://[^\s\"'<>)]{1,4000}", I)
LONG_VALUE = re.compile(r"[?&][\w-]{1,20}=([A-Za-z0-9+/_%=-]{120,})")


def _md_exfil(text: str):
    """A markdown image whose query string carries a template placeholder (data the agent would fill in)."""
    for m in MD_IMAGE.finditer(text):
        url = m.group(1)
        q = url.find("?")
        if q >= 0 and "=" in url[q:] and PLACEHOLDER.search(url, q):
            return m
    return None


def _url_smuggling(text: str):
    for m in URL.finditer(text):
        if LONG_VALUE.search(m.group(0)):
            return m
    return None


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _excerpt(text: str, start: int, end: int, mask: bool = False) -> str:
    s, e = max(0, start - 50), min(len(text), end + 50)
    mid = text[start:end]
    if mask:
        mid = mid[:4] + "…" + ("*" * 4)
    return (text[s:start] + mid + text[end:e]).replace("\n", " ")[:240]


def _decoded_views(text: str) -> Iterable[tuple[str, str]]:
    """Yield (label, text) for base64 blobs that decode to readable text, so encoded instructions are seen too."""
    for m in list(LONG_B64.finditer(text))[:5]:
        try:
            raw = base64.b64decode(m.group(0) + "=" * (-len(m.group(0)) % 4), validate=False)
            dec = raw.decode("utf-8")
        except Exception:
            continue
        if sum(c.isprintable() or c.isspace() for c in dec) / max(1, len(dec)) > 0.95:
            yield "base64", dec


def inspect(text: str, direction: str = "inbound") -> dict:
    if direction not in ("inbound", "outbound"):
        raise ValueError("direction must be inbound or outbound")
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    text = text[:MAX_CHARS]
    findings: list[dict] = []

    def add(sev, code, detail, ev=None):
        if any(f["code"] == code for f in findings):
            return
        f = {"severity": sev, "code": code, "detail": detail}
        if ev:
            f["evidence"] = ev
        findings.append(f)

    redactions: list[tuple[int, int, str]] = []

    if direction == "inbound":
        views = [("text", text)] + list(_decoded_views(text))
        for label, body in views:
            for sev, code, why, rx in INBOUND:
                for m in rx.finditer(body):
                    before = body[max(0, m.start() - 120):m.start()]
                    quoted = body[max(0, m.start() - 2):m.start()].strip()[-1:] in ("'", '"', "“", "(")
                    s = sev
                    if label == "text" and sev == "high" and (DESCRIBES.search(before) or quoted):
                        s = "low"     # talks about the attack (an article, a scanner, a docs page): note, don't block
                    note = why + (" (inside base64-encoded text)" if label == "base64" else "")
                    add(s, code if s != "low" else code + "_mentioned", note, _excerpt(body, m.start(), m.end()))
                    break
        if HIDDEN_CHARS.search(text) or ANSI.search(text):
            n = len(HIDDEN_CHARS.findall(text)) + len(ANSI.findall(text))
            add("medium" if n < 20 else "high", "hidden_characters", f"{n} invisible or terminal-control characters")
        m = HIDDEN_HTML.search(text)
        hc = None if m else _hidden_comment(text)
        if m or hc:
            st, en = (m.start(), m.end()) if m else hc
            add("medium", "hidden_html", "HTML that is invisible to a person but read by the agent", _excerpt(text, st, min(en, st + 120)))
        m = _md_exfil(text)
        if m:
            add("high", "markdown_exfiltration", "a markdown image whose URL would carry data out when rendered", _excerpt(text, m.start(), m.end()))
        if len(views) > 1 and not any("base64" in f["detail"] for f in findings):
            add("info", "encoded_text", "contains base64 that decodes to readable text")
    else:
        for code, what, rx in SECRETS:
            for m in rx.finditer(text):
                add("high", code, f"contains {what}", _excerpt(text, m.start(), m.end(), mask=True))
                redactions.append((m.start(), m.end(), code))
        for m in CARD.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and _luhn(digits) and len(set(digits)) > 1:
                add("high", "card_number", "contains a payment card number", _excerpt(text, m.start(), m.end(), mask=True))
                redactions.append((m.start(), m.end(), "card_number"))
        for m in SSN.finditer(text):
            add("medium", "us_ssn", "contains what looks like a US Social Security number", _excerpt(text, m.start(), m.end(), mask=True))
            redactions.append((m.start(), m.end(), "us_ssn"))
        m = _url_smuggling(text)
        if m:
            add("medium", "url_data_smuggling", "a URL carrying a long encoded value in its query string", _excerpt(text, m.start(), min(m.end(), m.start() + 160)))
        m = _md_exfil(text)
        if m:
            add("high", "markdown_exfiltration", "a markdown image whose URL would carry data out when rendered", _excerpt(text, m.start(), m.end()))
        if HIDDEN_CHARS.search(text):
            add("medium", "hidden_characters", "invisible characters in outgoing text (possible watermark or smuggled data)")

    risk = min(100, sum(WEIGHT[f["severity"]] for f in findings))
    verdict = "block" if any(f["severity"] == "high" for f in findings) else "warn" if risk >= 25 else "allow"
    out = {"verdict": verdict, "risk": risk, "direction": direction, "findings": findings,
           "chars": len(text), "units": units_for(text), "engine": ENGINE_VERSION,
           "input_sha256": hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()}
    if redactions:
        out["redacted_text"] = redact(text, redactions)
    return out


def redact(text: str, spans: list[tuple[int, int, str]]) -> str:
    out, last = [], 0
    for s, e, code in sorted(set(spans)):
        if s < last:
            continue
        out.append(text[last:s])
        out.append(f"[REDACTED:{code}]")
        last = e
    out.append(text[last:])
    return "".join(out)


def units_for(text: str) -> int:
    return max(1, -(-len(text) // UNIT_CHARS))
