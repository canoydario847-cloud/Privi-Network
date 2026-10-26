# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Call - https://priviflow.us - dariocanoy@priviflow.us
"""The Privi phone line: a voice agent that answers calls through Twilio.

Cheapest workable setup: Twilio's own speech recognition (<Gather input="speech">) and
text-to-speech (<Say>), so there is no streaming server or paid speech API. Most questions are
answered from a fixed script at no extra cost; only when a caller asks something the script
does not cover, and ANTHROPIC_API_KEY is set, a small model writes a two-sentence answer.
Callers can leave a pilot request (transcribed into the call log) or be put through to Dario.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

MAX_TURNS = 5

GREETING = ("Thanks for calling Privi, trust infrastructure for AI agents and manufacturers, from Port Huron, Michigan. "
            "I'm the Privi agent. Ask me anything, or say: pricing, manufacturing, government, developers, "
            "or say pilot to request one. Say Dario, or press zero, to reach the founder.")

ANSWERS = {
    "pricing": ("Privi has a free plan with 500 audit entries a month. Ledger Pro is 29 dollars a month in USDC. "
                "Pay-per-call tools cost one to ten cents, and routing a call through the Privi network costs a tenth of a cent "
                "after 50 free calls a day."),
    "manufacturing": ("Privi ChainFlow and Privi Verify give small manufacturers a tamper-proof record of every lot: "
                      "where it was made, who handled it, and whether it was recalled. Buyers and their AI agents can check a lot in one call."),
    "government": ("For government teams, Privi Ledger builds the A I use-case inventory and the post-quantum migration plan "
                   "the new federal memos ask for, sealed and anchored on chain so auditors can verify them."),
    "developers": ("Developers connect any MCP client to privi dash ledger dot on render dot com slash M C P. "
                   "Everything is listed at privi dash hub dot on render dot com. Signup is free."),
    "agents": ("The Privi Call network lets any A I agent call any other agent with one number, and every call is logged and "
               "sealed on chain. Agents register for free at privi dash call dot on render dot com."),
    "security": ("Privi signs records with post-quantum signatures, chains every entry, and anchors the chain on the Privi Devnet, "
                 "so a record cannot be changed later without everyone seeing it."),
    "about": ("Privi World Co was founded by Dario Canoy in Port Huron, Michigan. "
              "It builds verifiable records, identity and payment controls for A I agents and the companies that run them."),
}

INTENTS = [
    ("human", r"\b(dario|founder|human|person|someone|representative|operator|owner|talk to)\b"),
    ("pilot", r"\b(pilot|demo|trial|sign me up|get started|buy|purchase|sales|quote)\b"),
    ("bye", r"\b(bye|goodbye|that'?s all|nothing else|no thanks|hang up)\b"),
    ("pricing", r"\b(price|pricing|cost|how much|plan|plans|fee|pay)\b"),
    ("manufacturing", r"\b(manufactur\w*|factory|factories|lot|lots|supply chain|recall|chainflow|traceab\w*|parts?)\b"),
    ("government", r"\b(government|federal|agency|omb|gov|public sector|inventory|compliance)\b"),
    ("developers", r"\b(developer|api|mcp|integrat\w*|code|sdk|connect)\b"),
    ("agents", r"\b(agent|agents|call network|network|register)\b"),
    ("security", r"\b(quantum|secure|security|tamper|blockchain|chain|crypto\w*)\b"),
    ("about", r"\b(who are you|what is privi|about|company|privi)\b"),
]
DIGITS = {"0": "human", "1": "pricing", "2": "pilot", "3": "manufacturing", "4": "government", "5": "developers"}


def intent(speech: str, digits: str = "") -> str:
    if digits:
        return DIGITS.get(digits[:1], "unknown")
    s = (speech or "").lower()
    for name, pat in INTENTS:
        if re.search(pat, s):
            return name
    return "unknown" if s.strip() else "silence"


def valid_signature(auth_token: str, url: str, params: dict[str, str], signature: str) -> bool:
    """Twilio request validation: base64(HMAC-SHA1(token, url + concatenated sorted key+value))."""
    if not auth_token or not signature:
        return False
    data = url + "".join(k + params[k] for k in sorted(params))
    expected = base64.b64encode(hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)


def ask_llm(api_key: str, model: str, question: str, timeout: float = 6.0) -> str | None:
    """Two short spoken sentences about Privi, or None (caller then hears the menu again)."""
    if not api_key:
        return None
    facts = " ".join(ANSWERS.values())
    body = {"model": model, "max_tokens": 120,
            "system": ("You are the Privi phone agent. Answer the caller in at most two short, plain sentences that "
                       "sound natural when spoken. Use only these facts; if they do not cover the question, say you "
                       "will pass it to Dario and suggest saying pilot or Dario. Never invent prices, customers or "
                       "results. Facts: " + facts),
            "messages": [{"role": "user", "content": question[:500]}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), method="POST",
                                 headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            msg = json.loads(r.read())
        text = " ".join(b.get("text", "") for b in msg.get("content", []) if b.get("type") == "text").strip()
        return text[:400] or None
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


# ---------------- TwiML ----------------

def _say(text: str, voice: str) -> str:
    return f'<Say voice="{escape(voice)}">{escape(text)}</Say>'


def gather(prompt: str, action: str, voice: str, hints: str = "pricing, pilot, Dario, manufacturing, government, developers") -> str:
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response>"
            f'<Gather input="speech dtmf" action="{escape(action)}" method="POST" speechTimeout="auto" numDigits="1" '
            f'timeout="6" language="en-US" hints="{escape(hints)}" actionOnEmptyResult="true">{_say(prompt, voice)}</Gather>'
            f"{_say('I did not catch that. You can also email dario canoy at priviflow dot u s. Goodbye.', voice)}"
            "</Response>")


def collect_lead(action: str, voice: str) -> str:
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response>"
            f'<Gather input="speech" action="{escape(action)}" method="POST" speechTimeout="3" timeout="8" language="en-US">'
            f"{_say('Great. Right after this, say your name, your company, what you need, and the best number or email to reach you.', voice)}"
            '</Gather>'
            f"{_say('I did not hear anything. Please call back or email dario canoy at priviflow dot u s.', voice)}</Response>")


def dial(number: str, caller_id: str, voice: str, fallback_action: str) -> str:
    cid = f' callerId="{escape(caller_id)}"' if caller_id else ""
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response>"
            f"{_say('Connecting you to Dario now.', voice)}"
            f'<Dial timeout="20" action="{escape(fallback_action)}" method="POST"{cid}>{escape(number)}</Dial></Response>')


def hangup(text: str, voice: str) -> str:
    return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response>{_say(text, voice)}<Hangup/></Response>"
