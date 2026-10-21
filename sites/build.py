#!/usr/bin/env python3
"""Generate the Privi product websites into sites/<name>/index.html.

Each folder is deployed as its own Render static site (publish path sites/<name>).
Edit SITES / URLS below and run `python3 sites/build.py`, then commit.
"""

import html
import json
from pathlib import Path

ROOT = Path(__file__).parent
LEDGER = "https://privi-ledger.onrender.com"
VERIFY = "https://privi-verify.onrender.com"
ANCHOR = "https://privi-anchor.onrender.com"
HUB = "https://privi-discovery.onrender.com"
REPO = "https://github.com/canoydario847-cloud/Privi-Network"
EMAIL = "dariocanoy@priviflow.us"
PASSPORT_ID = "pp_0be5f707a050950e"
OWNER_WALLET = "0x1990589FD200E043b8C6FD9ec5956c61b3071048"

# Public URL of each site (custom domains on Render; each also answers at privi-<name>.onrender.com).
URLS = {
    "home": "https://priviflow.us",
    "fortress": "https://fortress.priviflow.us",
    "passport": "https://passport.priviflow.us",
    "kya": "https://kya.priviflow.us",
    "mandates": "https://mandates.priviflow.us",
    "gov": "https://gov.priviflow.us",
    "chainflow": "https://chainflow.priviflow.us",
    "developers": "https://developers.priviflow.us",
}
NAV = [("home", "Privi"), ("fortress", "Fortress"), ("passport", "Passport"), ("kya", "KYA"),
       ("mandates", "Mandates"), ("gov", "Government"), ("chainflow", "ChainFlow"), ("developers", "Developers")]

e = html.escape

CSS = """
:root{--paper:#F7F8FA;--surface:#FFFFFF;--ink:#0E1B33;--steel:#5A6B85;--seal:#2F5BEA;--on-seal:#FFFFFF;--verified:#0F8A5F;--rule:#DCE1EA;--code:#EEF1F6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:#0D1626;--surface:#122036;--ink:#E7ECF4;--steel:#93A3BB;--seal:#7FA2FF;--on-seal:#0D1626;--verified:#3CCB94;--rule:#22314A;--code:#16263F}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.6 "IBM Plex Sans",system-ui,sans-serif}
a{color:var(--seal);text-underline-offset:3px}a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid var(--seal);outline-offset:2px}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
header{border-bottom:1px solid var(--rule);background:var(--surface)}
.bar{display:flex;align-items:center;gap:24px;min-height:64px;flex-wrap:wrap}
.mark{font:600 20px "IBM Plex Sans Condensed",sans-serif;color:var(--ink);text-decoration:none;letter-spacing:.01em;display:flex;align-items:center;gap:10px}
.mark svg{width:26px;height:26px}
nav{display:flex;gap:4px 18px;flex-wrap:wrap;font-size:15px}nav a{color:var(--steel);text-decoration:none;padding:4px 0}
nav a[aria-current]{color:var(--ink);box-shadow:inset 0 -2px var(--seal)}nav a:hover{color:var(--ink)}
.hero{display:grid;grid-template-columns:1.15fr .85fr;gap:48px;padding:72px 0 56px;align-items:start}
h1{font:600 clamp(36px,5.2vw,58px)/1.04 "IBM Plex Sans Condensed",sans-serif;margin:0 0 20px;letter-spacing:-.01em;max-width:16ch}
h2{font:600 30px/1.15 "IBM Plex Sans Condensed",sans-serif;margin:0 0 14px}
h3{font:600 20px/1.3 "IBM Plex Sans Condensed",sans-serif;margin:0 0 4px}
.lede{font-size:20px;color:var(--steel);max-width:36em;margin:0 0 28px}
.cta{display:flex;gap:14px;flex-wrap:wrap}
.btn{display:inline-block;padding:12px 20px;border-radius:8px;background:var(--seal);color:var(--on-seal);text-decoration:none;font-weight:600}
.btn.alt{background:transparent;color:var(--ink);box-shadow:inset 0 0 0 1.5px var(--rule)}
.proof{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:22px}
.proof h2{font-size:18px;margin:0 0 4px}.proof p{margin:0 0 14px;color:var(--steel);font-size:15px}
.root{font:500 clamp(15px,1.9vw,19px)/1.55 "IBM Plex Mono",monospace;word-break:break-all;color:var(--ink);margin:6px 0 14px}
.root span{display:inline-block;margin-right:.45em}
.facts{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:15px;margin:0}.facts dt{color:var(--steel)}.facts dd{margin:0}
.ok{color:var(--verified);font-weight:600}.wait{color:var(--steel)}.root .wait{font:15px/1.5 "IBM Plex Sans",system-ui,sans-serif;word-break:normal}
section{padding:56px 0;border-top:1px solid var(--rule)}
.prose{max-width:44em}.prose p{margin:0 0 16px}
dl.defs{display:grid;grid-template-columns:minmax(180px,260px) 1fr;gap:22px 40px;margin:28px 0 0}
dl.defs dt{font:600 19px/1.3 "IBM Plex Sans Condensed",sans-serif}dl.defs dd{margin:0;color:var(--steel)}
ol.steps{counter-reset:s;list-style:none;padding:0;margin:24px 0 0;max-width:46em}
ol.steps li{counter-increment:s;position:relative;padding:0 0 22px 52px}
ol.steps li::before{content:counter(s);position:absolute;left:0;top:0;width:34px;height:34px;border-radius:50%;border:1.5px solid var(--seal);color:var(--seal);font:600 15px/31px "IBM Plex Sans Condensed",sans-serif;text-align:center}
pre{background:var(--code);border-radius:10px;padding:18px;overflow-x:auto;font:14px/1.6 "IBM Plex Mono",monospace;margin:18px 0 0}
code{font-family:"IBM Plex Mono",monospace;font-size:.9em}
.note{font-size:15px;color:var(--steel);max-width:44em}
form.check{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 10px}
form.check input{flex:1 1 280px;padding:11px 12px;border:1.5px solid var(--rule);border-radius:8px;background:var(--surface);color:var(--ink);font:15px "IBM Plex Mono",monospace}
form.check button{padding:11px 18px;border:0;border-radius:8px;background:var(--seal);color:var(--on-seal);font:600 15px "IBM Plex Sans",sans-serif;cursor:pointer}
#out{font-size:15px;max-width:44em}
footer{border-top:1px solid var(--rule);padding:36px 0 48px;color:var(--steel);font-size:15px}
footer .cols{display:flex;gap:40px;flex-wrap:wrap;justify-content:space-between}
@media (max-width:820px){.hero{grid-template-columns:1fr;padding-top:44px}dl.defs{grid-template-columns:1fr;gap:6px}dl.defs dd{margin-bottom:14px}}
@media (prefers-reduced-motion:no-preference){.root.fresh span{animation:in .5s ease both}@keyframes in{from{opacity:0}to{opacity:1}}}
"""

LOGO = ('<svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="14" fill="#0E1B33"/>'
        '<path d="M18 46V18h14a10 10 0 0 1 0 20h-6v8z" fill="none" stroke="#7FA2FF" stroke-width="5" stroke-linejoin="round"/>'
        '<circle cx="46" cy="44" r="4" fill="#3CCB94"/></svg>')

STH_WIDGET = f"""
<aside class="proof" aria-live="polite">
  <h2>Live from Privi Ledger</h2>
  <p>The current root of Privi's transparency log. Every action recorded by every organization is a leaf in this tree.</p>
  <div class="root" id="root"><span class="wait">Loading the latest signed tree head…</span></div>
  <dl class="facts">
    <dt>Entries</dt><dd id="size">…</dd>
    <dt>Signed</dt><dd id="signed">…</dd>
    <dt>On chain</dt><dd id="chain">…</dd>
  </dl>
  <p style="margin:14px 0 0"><a href="{LEDGER}/log/sth">See the raw signed tree head</a></p>
</aside>
<script>
fetch("{LEDGER}/log/sth").then(r=>r.json()).then(d=>{{
  const h=d.tree_head, root=document.getElementById("root");
  root.innerHTML=h.root_hash.match(/.{{8}}/g).map(x=>"<span>"+x+"</span>").join(""); root.classList.add("fresh");
  document.getElementById("size").textContent=h.tree_size.toLocaleString()+" entries, "+new Date(h.timestamp).toUTCString().replace(" GMT"," UTC");
  document.getElementById("signed").innerHTML='<span class="ok">Ed25519 + ML-DSA-87</span>';
  const a=d.anchor; document.getElementById("chain").innerHTML=a&&a.block_number?'<span class="ok">Anchored, Privi block '+a.block_number+'</span>':'Anchored every 15 minutes';
}}).catch(()=>{{document.getElementById("root").innerHTML='<span class="wait">Privi Ledger is waking up. Refresh in a few seconds.</span>'}});
</script>"""


def page(key, title, desc, h1, lede, ctas, aside, body, extra_head=""):
    nav = "".join(f'<a href="{URLS[k]}"{" aria-current=page" if k == key else ""}>{e(n)}</a>' for k, n in NAV)
    cta = "".join(f'<a class="btn{" alt" if i else ""}" href="{u}">{e(t)}</a>' for i, (t, u) in enumerate(ctas))
    ld = {"@context": "https://schema.org", "@type": "WebPage", "name": title, "description": desc, "url": URLS[key],
          "publisher": {"@type": "Organization", "name": "Privi World Co", "url": URLS["home"], "email": EMAIL,
                        "founder": {"@type": "Person", "name": "Dario Canoy"}}}
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}">
<link rel="canonical" href="{URLS[key]}"><link rel="icon" href="favicon.svg" type="image/svg+xml"><link rel="alternate" type="text/plain" href="{HUB}/llms.txt" title="llms.txt">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@600&family=IBM+Plex+Sans:wght@400;600&display=swap" rel="stylesheet">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:type" content="website">
<script type="application/ld+json">{json.dumps(ld)}</script>{extra_head}
<style>{CSS}</style></head><body>
<header><div class="wrap bar"><a class="mark" href="{URLS['home']}">{LOGO}Privi</a><nav aria-label="Privi sites">{nav}</nav></div></header>
<main><div class="wrap">
<div class="hero"><div><h1>{e(h1)}</h1><p class="lede">{lede}</p><div class="cta">{cta}</div></div>{aside}</div>
{body}
</div></main>
<footer><div class="wrap cols"><div><strong>Privi World Co</strong><br>Port Huron, Michigan<br><a href="mailto:{EMAIL}">{EMAIL}</a></div>
<div>Built by Dario Canoy<br><a href="{REPO}">Source on GitHub</a><br><a href="{HUB}/llms.txt">For AI agents: llms.txt</a></div>
<div>MCP servers<br><a href="{LEDGER}">Ledger</a>, <a href="{VERIFY}">Verify</a>, <a href="{ANCHOR}">Anchor</a></div></div></footer>
</body></html>"""


def defs(items):
    return '<dl class="defs">' + "".join(f"<dt>{e(t)}</dt><dd>{d}</dd>" for t, d in items) + "</dl>"


def steps(items):
    return '<ol class="steps">' + "".join(f"<li><h3>{e(t)}</h3>{d}</li>" for t, d in items) + "</ol>"


def sec(title, inner, intro=""):
    return f'<section><h2>{e(title)}</h2>{f"<div class=prose><p>{intro}</p></div>" if intro else ""}{inner}</section>'


MCP_SNIPPET = f"""<pre>{{
  "mcpServers": {{
    "privi-ledger": {{ "url": "{LEDGER}/mcp" }},
    "privi-verify": {{ "url": "{VERIFY}/mcp" }},
    "privi-anchor": {{ "url": "{ANCHOR}/mcp" }}
  }}
}}</pre>"""

SITES = {}

SITES["home"] = page(
    "home", "Privi: proof for everything your AI agents do",
    "Privi gives AI agents a tamper-evident record, a trust credential, wallet checks and spending mandates, all verifiable on chain.",
    "Proof for everything your AI agents do",
    "Privi records what agents do in a log nobody can quietly rewrite, then turns that history into credentials other companies can check in one call. Every proof is signed twice, once with a post-quantum algorithm, and anchored on the Privi chain.",
    [("Start free", URLS["developers"]), ("Talk to the founder", f"mailto:{EMAIL}")],
    STH_WIDGET,
    sec("What Privi does", defs([
        ("Ledger", "An append-only, hash-linked log of every agent action. Edits, deletions and reordering are detectable. Sealed compliance reports export as PDF."),
        ("Fortress", f"Defense-grade controls: ML-DSA-87 post-quantum signatures, an RFC 9162 transparency log, two-person approval for sensitive actions and evidence you can verify offline. <a href='{URLS['fortress']}'>About Fortress</a>"),
        ("Passport", f"A signed trust score for an agent, 0 to 1000, computed from its verified history and re-checked live every time someone looks. <a href='{URLS['passport']}'>About Passport</a>"),
        ("KYA", f"Know Your Agent for blockchains: is this wallet run by an audited agent? Free to check, with a signed answer. <a href='{URLS['kya']}'>About KYA</a>"),
        ("Mandates", f"A person's signed permission for an agent to spend: budget, per-payment cap, payees and expiry, checkable by any merchant. <a href='{URLS['mandates']}'>About Mandates</a>"),
        ("Government", f"OMB M-25-21 AI use-case inventories and EO 14409 post-quantum migration plans, sealed on chain. <a href='{URLS['gov']}'>For agencies</a>"),
        ("ChainFlow", f"Lot provenance and chain of custody for manufacturers, paid per check in USDC. <a href='{URLS['chainflow']}'>For manufacturers</a>"),
    ]))
    + sec("Why it can be trusted", steps([
        ("Every action is chained", "<p>Each entry's SHA-256 fingerprint covers the one before it, so changing history breaks the chain at the exact point it was touched.</p>"),
        ("The whole log is a Merkle tree", "<p>Anyone can get a proof that an entry is in the log, and that the log only grew between two points in time. No trust in Privi required.</p>"),
        ("The tree is sealed on chain", "<p>Tree heads and checkpoints are anchored on the Privi EVM chain, so even Privi cannot rewrite the past without it showing.</p>"),
    ]))
    + sec("Built for agents first", MCP_SNIPPET + f"<p class='note'>Agents connect over MCP. Paid tools settle in USDC on Base through x402, with no account needed. Humans start on the <a href='{URLS['developers']}'>developer site</a>.</p>"),
)

SITES["fortress"] = page(
    "fortress", "Privi Fortress: defense-grade integrity for AI agent records",
    "Post-quantum ML-DSA-87 signatures, an RFC 9162 transparency log, two-person integrity and offline-verifiable evidence for AI agent audit trails.",
    "Audit trails built to survive an adversary",
    "Fortress assumes someone will try to alter the record, possibly with a quantum computer, possibly from inside. It answers with post-quantum signatures, a public transparency log, two-person control and evidence that verifies with no network at all.",
    [("Read the controls", "#controls"), ("Get the offline verifier", f"{LEDGER}/tools/verify_bundle.py")],
    STH_WIDGET,
    f'<section id="controls"><h2>Four controls</h2>' + defs([
        ("Post-quantum signatures", "Every Privi attestation is signed with Ed25519 and with ML-DSA-87, the NIST FIPS 204 parameter set that NSA's CNSA 2.0 suite requires for national security systems. A future quantum computer that breaks elliptic curves still cannot forge Privi's history."),
        ("Transparency log", "All entries from all organizations form one append-only Merkle tree, the design behind Certificate Transparency (RFC 9162). Free inclusion proofs show an entry is in the log. Free consistency proofs show the log only grew."),
        ("Two-person integrity", "Sensitive actions wait for distinct, wallet-signed approvals from named officers. The same officer cannot approve twice, outsiders are refused, any officer can veto, and an authorization works exactly once."),
        ("Air-gapped evidence", "Export a stream as a dual-signed bundle. A single Python script checks every entry, the hash chain, the inclusion proof and both signatures without touching the network."),
    ]) + "</section>"
    + sec("How two-person integrity works", steps([
        ("Set a policy", "<p>Name the officers' wallets and how many must approve, for example 2 of 3 for treasury transfers.</p>"),
        ("The agent asks", "<p>Before acting, the agent files a request describing exactly what it will do. The exact parameters are hashed into what officers sign.</p>"),
        ("Officers sign", "<p>Each officer opens the approval page and signs with their own wallet. One veto blocks the action.</p>"),
        ("The agent executes once", "<p>Only an authorized request can be used, only once, and every step lands in the tamper-evident log.</p>"),
    ]))
    + sec("Verify it yourself", f"""<pre>curl -s {LEDGER}/log/sth
curl -s "{LEDGER}/log/inclusion?hash=&lt;entry_hash&gt;"
python verify_bundle.py bundle.json</pre>""",
          "Nothing here asks you to take our word for it. Fetch the signed tree head, request a proof, or run the offline verifier on an exported bundle.")
    + sec("What Fortress is, precisely", "",
          "Fortress implements engineering controls aligned with CNSA 2.0 and NIST SP 800-53 (AU-9, AU-10, AC-5, SC-13). It is not a certification: Privi does not claim FIPS 140-3 module validation, FedRAMP authorization or a DoD Impact Level. Agencies and contractors pursuing those can use Fortress evidence in their own packages."),
)

SITES["passport"] = page(
    "passport", "Privi Passport: a trust score for AI agents",
    "A signed, on-chain-anchored credential that scores an AI agent 0 to 1000 from its verified history, re-checked live on every lookup.",
    "Know which agents to trust before they act",
    "A Privi Passport scores an agent or organization from 0 to 1000 using evidence only a verified record can provide. It is signed twice, anchored on chain, and re-scored live, so a passport stops vouching the moment the history behind it is tampered with.",
    [("See a live passport", f"{LEDGER}/passports/{PASSPORT_ID}"), ("Issue one", URLS["developers"])],
    f"""<aside class="proof" aria-live="polite"><h2>Privi World Co's passport</h2><p>Fetched live and re-scored just now.</p>
<div class="root" id="pp" style="font-size:44px;font-family:'IBM Plex Sans Condensed',sans-serif">…</div>
<dl class="facts"><dt>Signature</dt><dd id="sig">…</dd><dt>History</dt><dd id="hist">…</dd><dt>On chain</dt><dd id="blk">…</dd></dl></aside>
<script>fetch("{LEDGER}/passports/{PASSPORT_ID}").then(r=>r.json()).then(d=>{{const v=d.verification,l=v.live||{{}};
document.getElementById("pp").textContent="Grade "+(l.grade||d.passport.grade)+", "+(l.score??d.passport.score)+" / 1000";
document.getElementById("sig").innerHTML=v.signature_valid?'<span class="ok">Valid Privi signature</span>':'Invalid';
document.getElementById("hist").innerHTML=v.history_still_intact?'<span class="ok">Intact since issue</span>':'Changed since issue';
document.getElementById("blk").textContent=d.attestation.anchored?"Privi block "+d.attestation.block_number:"Pending";}}).catch(()=>{{document.getElementById("pp").textContent="Waking up, refresh shortly"}});</script>""",
    sec("What the score is made of", defs([
        ("History, 300", "How much verified activity exists, and over how many days."),
        ("Integrity, 250", "Every hash chain still verifies. All or nothing."),
        ("Anchoring, 150", "Share of the agent's streams whose on-chain checkpoint matches the record."),
        ("Reliability, 100", "One minus the failure rate."),
        ("Oversight, 50", "Human approvals recorded on payments, data changes and messages."),
        ("Compliance, 100", "A sealed compliance report exists and is clean."),
        ("Handshakes, 50", "Deals other Privi organizations confirmed on both sides."),
    ]), "Every point is itemised in the passport, so a counterparty can see exactly why an agent scored what it did. Grades: A from 850, B from 700, C from 550, D from 400.")
    + sec("Gate a deal in one call", f"<pre>passport_gate(passport_id=\"{PASSPORT_ID}\", min_grade=\"C\", purpose=\"pay invoice 1042\")</pre>",
          "Before paying or trusting another agent, ask for its passport and apply your minimum. If you send your own key, the decision is written to your log as due-diligence evidence."),
)

SITES["kya"] = page(
    "kya", "Privi KYA: Know Your Agent for blockchain wallets",
    "Check whether a blockchain wallet is operated by an audited AI agent, with a free, signed answer for chains, exchanges and payment facilitators.",
    "Is this wallet run by an audited agent?",
    "Banks have Know Your Customer. As AI agents become the senders of on-chain transactions, chains, exchanges and payment facilitators need Know Your Agent. Privi KYA resolves any wallet to its organization and live Passport, and answers with a signed allow or deny.",
    [("Check a wallet", "#check"), ("Bind your wallet", f"{LEDGER}/kya/connect")],
    f"""<aside class="proof" id="check"><h2>Check any wallet</h2><p>Free, no key. The answer is signed by Privi and valid for 60 minutes.</p>
<form class="check" id="f"><label for="a" class="sr" style="position:absolute;left:-9999px">Wallet address</label>
<input id="a" value="{OWNER_WALLET}" spellcheck="false" autocomplete="off"><button>Check wallet</button></form><div id="out"></div></aside>
<script>document.getElementById("f").onsubmit=async ev=>{{ev.preventDefault();const o=document.getElementById("out");o.textContent="Checking…";
try{{const d=await (await fetch("{LEDGER}/kya/"+encodeURIComponent(document.getElementById("a").value.trim())+"?min_score=0")).json();
if(d.error){{o.textContent=d.error;return}}
o.innerHTML=d.allow?'<span class="ok">Allowed.</span> '+d.organization+', grade '+d.current_grade+' ('+d.current_score+'), ownership proven by '+d.proof+'.':'<strong>Not allowed.</strong> '+(d.reasons||[]).join("; ");}}catch(e){{o.textContent="Privi Ledger is waking up. Try again in a few seconds."}}}};</script>""",
    sec("How a wallet gets bound", steps([
        ("Request a challenge", "<p>The organization asks Privi for a message naming the wallet and the organization.</p>"),
        ("Sign it with the wallet", "<p>The wallet's owner signs once in MetaMask or any EVM wallet. It is free and sends no transaction.</p>"),
        ("Privi verifies the signature", "<p>Privi recovers the signer from the signature. Only a match binds the wallet, and a proven wallet cannot be claimed by anyone else.</p>"),
    ]))
    + sec("For chains, exchanges and facilitators", f"<pre>GET {LEDGER}/kya/&lt;address&gt;?min_grade=C&amp;require_signed=true</pre>",
          "Call this before accepting an agent transaction. Keep the returned attestation and its Ed25519 and ML-DSA-87 signatures as your compliance record."),
)

SITES["mandates"] = page(
    "mandates", "Privi Mandates: signed permission for AI agents to spend",
    "A person's wallet-signed authorization for an AI agent to spend, with budget, caps, payees and expiry that any merchant can check for free.",
    "Let agents spend. Within limits a person signed.",
    "When an agent pays on someone's behalf, the merchant needs to know a human agreed. A Privi Mandate is that agreement: plain-English terms the person signs once with their wallet, enforced on every payment and checkable by anyone for free.",
    [("How it works", "#how"), ("Use it in your agent", URLS["developers"])],
    """<aside class="proof"><h2>A mandate says</h2><p>The exact text a person signs.</p>
<pre style="margin:0;white-space:pre-wrap">I authorize ShopBot's agent 'shopper' to spend up to 100 USDC in total, at most 40 USDC per payment, to only these payees: store.example.com, until 2026-11-20 UTC.
Purpose: Buy office supplies.
I can revoke this at any time.</pre></aside>""",
    f'<section id="how"><h2>How it works</h2>' + steps([
        ("The agent drafts terms", "<p>Budget, per-payment cap, allowed payees by address or domain, expiry and purpose. Privi returns a signing link.</p>"),
        ("The person signs once", "<p>They read the terms in plain English and sign with their wallet. Privi countersigns and anchors the terms on chain.</p>"),
        ("Every payment is checked", "<p>Before paying, the agent records the spend. Over-cap, wrong-payee, expired or revoked payments are refused and logged as blocked.</p>"),
        ("Merchants verify for free", "<p>A merchant or facilitator checks the mandate and gets a signed allow or deny with the remaining budget.</p>"),
    ]) + "</section>"
    + sec("Check a mandate", f"<pre>GET {LEDGER}/mandates/&lt;mandate_id&gt;/check?amount=25&amp;payee=store.example.com</pre>",
          "The person can revoke from the same page they signed on, with one more signature. Revocation takes effect immediately for every checker."),
)

SITES["gov"] = page(
    "gov", "Privi for government: AI inventories and post-quantum readiness",
    "Tamper-evident OMB M-25-21 AI use-case inventories and EO 14409 post-quantum migration plans, sealed on chain, with defense-grade Fortress controls.",
    "Inventories and plans an inspector general can verify",
    "Agencies must inventory their AI use cases and plan their move to post-quantum cryptography. Privi keeps both as versioned, tamper-evident records, checks them against the requirements before you submit, and seals each export on chain.",
    [("Contact us", f"mailto:{EMAIL}?subject=Privi%20for%20government"), ("Fortress controls", URLS["fortress"])],
    STH_WIDGET,
    sec("What agencies get", defs([
        ("AI use-case inventory", "Records in OMB M-25-21 reporting fields. Every change is a new version in the tamper-evident log, and a readiness check flags missing fields, PII without a privacy impact assessment and high-impact AI missing minimum risk practices."),
        ("Post-quantum migration", "Classify each system's cryptography, record quantum-vulnerable assets and get a prioritized migration plan aligned with EO 14409 and OMB M-26-15. Exports are sealed on chain."),
        ("Two-person integrity", "Require two officers' signatures before an agent changes the inventory, publishes an export or takes any other sensitive step."),
        ("Evidence for oversight", "Hand an inspector a dual-signed bundle they can verify on an air-gapped machine."),
    ]))
    + sec("Plain about certification", "",
          "Privi is an early-stage company. It does not yet hold FedRAMP authorization, a DoD Impact Level or FIPS 140-3 module validation. Fortress controls are designed to support those efforts, and pilots with agencies and contractors are welcome."),
)

SITES["chainflow"] = page(
    "chainflow", "Privi ChainFlow: verifiable lot provenance for manufacturers",
    "Tamper-evident chain of custody for manufactured lots, checkable by buyers and their AI agents per call in USDC.",
    "Prove where every lot came from",
    "ChainFlow records each lot's journey, from received to produced, inspected and shipped, in a chain no one can quietly edit. Buyers and their agents verify provenance per check, paid in USDC, with no account.",
    [("Verify a lot", URLS["developers"]), ("Pilot ChainFlow", f"mailto:{EMAIL}?subject=ChainFlow%20pilot")],
    STH_WIDGET,
    sec("Built for small manufacturers", defs([
        ("Record events", "Each receiving, production, inspection and shipping event is linked to the previous one by a SHA-256 fingerprint."),
        ("Anchored on chain", "Lot fingerprints are checkpointed on the Privi chain every few minutes."),
        ("Paid per check", "Buyers' agents pay a few cents in USDC on Base per verification through x402. Lookups by fingerprint are free."),
        ("Michigan first", "Built in Port Huron for the manufacturers around it, open to anyone."),
    ]))
    + sec("For buyers' agents", f"<pre>privi_verify_lot(lot_id=\"DEMO-STEEL-0001\")\nprivi_chain_of_custody(lot_id=\"DEMO-STEEL-0001\")</pre><p class='note'>MCP endpoint: <code>{VERIFY}/mcp</code></p>"),
)

SITES["developers"] = page(
    "developers", "Privi for developers: MCP servers for agent trust",
    "Connect AI agents to Privi Ledger, Verify and Anchor over MCP. Free tier, x402 payments in USDC, every proof verifiable.",
    "Connect your agent in one config block",
    "Privi runs as three MCP servers. Point your agent at them, sign up for a free organization from inside the agent, and start recording actions. Upgrades and paid checks settle in USDC on Base through x402.",
    [("Add the servers", "#connect"), ("Read llms.txt", f"{HUB}/llms.txt")],
    STH_WIDGET,
    f'<section id="connect"><h2>Add the servers</h2>{MCP_SNIPPET}<p class="note">All three are also listed in the official MCP Registry as io.github.canoydario847-cloud/privi-ledger, privi-verify and privi-anchor.</p></section>'
    + sec("First five minutes", steps([
        ("Sign up from the agent", "<p>Call <code>ledger_signup</code> with your company name. The response contains your organization key, shown once.</p>"),
        ("Send the key", "<p>Every request carries <code>Authorization: Bearer &lt;key&gt;</code>. The free plan includes 500 entries a month.</p>"),
        ("Record actions", "<p>Call <code>ledger_record_action</code> after each tool call, payment, message or decision. Keep the returned entry hash as a receipt.</p>"),
        ("Prove it", "<p>Issue a passport, export an evidence bundle or hand anyone an inclusion proof.</p>"),
    ]))
    + sec("Tools by job", defs([
        ("Record and audit", "ledger_record_action, ledger_read_stream, ledger_audit_stream, ledger_compliance_report, ledger_report_pdf"),
        ("Fortress", "fortress_keys, ledger_tree_head, ledger_inclusion_proof, ledger_consistency_proof, fortress_tpi_policy, fortress_tpi_request, fortress_tpi_execute, ledger_evidence_bundle"),
        ("Trust", "passport_issue, passport_verify, passport_gate, kya_check, kya_bind_wallet"),
        ("Payments", "mandate_create, mandate_spend, mandate_check, ledger_upgrade_pro"),
        ("Between companies", "ledger_handshake_offer, ledger_handshake_accept, ledger_handshake_verify"),
        ("Government", "gov_ai_usecase_save, gov_ai_inventory_check, gov_pqc_plan, gov_pqc_export"),
        ("Proof of existence", "anchor_hash_text, anchor_hashes, anchor_verify (Privi Anchor)"),
    ]))
    + sec("Pricing", defs([
        ("Free", "500 entries a month, every tool included."),
        ("Pro", "29 USDC per 30 days through x402, unlimited entries, passports included."),
        ("Pay per check", "Audits and lot verification cost cents in USDC, no account needed."),
    ])),
)


def main():
    for key, htmldoc in SITES.items():
        d = ROOT / key
        d.mkdir(exist_ok=True)
        (d / "index.html").write_text(htmldoc, encoding="utf-8")
        (d / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {URLS[key]}/sitemap.xml\n", encoding="utf-8")
        (d / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                       f"<url><loc>{URLS[key]}/</loc></url></urlset>", encoding="utf-8")
        (d / "favicon.svg").write_text(LOGO.replace(' aria-hidden="true"', ' xmlns="http://www.w3.org/2000/svg"'), encoding="utf-8")
        print("built", key)


if __name__ == "__main__":
    main()
