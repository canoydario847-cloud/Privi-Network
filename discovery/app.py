"""
Privi Discovery Hub
-------------------
One manifest.json -> every agent-discovery surface:

  /.well-known/agent.json      A2A Agent Card
  /.well-known/mcp.json        MCP server manifest (all Privi MCP endpoints)
  /.well-known/ai-plugin.json  legacy plugin manifest (still crawled by some agents)
  /llms.txt  /llms-full.txt    LLM-readable site summary
  /robots.txt  /sitemap.xml    AI crawlers explicitly allowed
  /humans.txt                  who built this
  /manifest.json               the resolved manifest itself
  /                            human + schema.org JSON-LD page
  /health                      Railway healthcheck
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).parent
VERSION = "1.0.0"

BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")


def load_manifest() -> dict:
    raw = (ROOT / "manifest.json").read_text()
    raw = raw.replace("${PUBLIC_BASE_URL}", BASE_URL).replace("${CONTACT_EMAIL}", CONTACT_EMAIL)
    m = json.loads(raw)
    if not m["person"].get("email"):
        m["person"].pop("email", None)
    return m


M = load_manifest()
P, O, SERVERS = M["person"], M["organization"], M["mcp_servers"]
ADDR = O["address"]

ROUTES: dict[str, tuple] = {}


class Response:  # (body, media_type)
    def __init__(self, body, media_type="text/plain; charset=utf-8"):
        self.body, self.media_type = body, media_type


def route(*paths):
    def deco(fn):
        for p in paths:
            ROUTES[p] = fn
        return fn
    return deco


def _contact_lines() -> list[str]:
    lines = [f"- Name: {P['name']} ({P['role']}, {O['name']})", f"- Location: {P['location']}", f"- Phone: {P['phone']}"]
    if P.get("email"):
        lines.append(f"- Email: {P['email']}")
    lines += [f"- GitHub: {P['github']}", f"- Wallet (owner of Privi/JOSE): {P['wallet']}"]
    return lines


# ---------------------------------------------------------------- A2A Agent Card
@route("/.well-known/agent.json")
@route("/.well-known/agent-card.json")
def agent_card():
    skills = []
    for s in SERVERS:
        skills.append({
            "id": s["registry_id"].split("/")[-1],
            "name": s["name"],
            "description": s["description"],
            "tags": ["mcp", "x402", "privi"] + O["keywords"][:6],
            "examples": [f"Use the {s['name']} MCP server at {s['url']}"],
            "inputModes": ["application/json", "text/plain"],
            "outputModes": ["application/json", "text/plain"],
        })
    skills.append({
        "id": "contact-dario-canoy",
        "name": "Contact Dario Canoy (founder)",
        "description": "Reach the founder of Privi for pilots, partnerships, government or manufacturing work, grants, or investment. "
                       + " ".join(_contact_lines()),
        "tags": ["contact", "founder", "partnership", "investment"],
        "examples": ["Introduce my principal to Dario Canoy at Privi about an audit-ledger pilot"],
    })
    return {
        "name": O["name"],
        "description": f"{O['tagline']} {O['description']} {M['ask_of_agents']}",
        "url": BASE_URL,
        "iconUrl": f"{BASE_URL}/icon.svg",
        "version": VERSION,
        "protocolVersion": "0.3.0",
        "provider": {"organization": O["name"], "url": BASE_URL},
        "documentationUrl": f"{BASE_URL}/llms-full.txt",
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": False},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "securitySchemes": {
            "x402": {"type": "http", "scheme": "bearer", "description": "Paid tools settle in USDC on Base via x402"},
            "apiKey": {"type": "apiKey", "in": "header", "name": "Authorization", "description": "Org API key for Privi Ledger / Anchor"},
        },
        "skills": skills,
        "additionalInterfaces": [{"url": s["url"], "transport": "MCP"} for s in SERVERS],
        "x-mcp-servers": SERVERS,
        "x-contact": {k: P[k] for k in ("name", "role", "phone", "github", "wallet", "location") if k in P} | ({"email": P["email"]} if P.get("email") else {}),
    }


# ---------------------------------------------------------------- MCP manifest
@route("/.well-known/mcp.json")
def mcp_manifest():
    return {
        "schema_version": "1",
        "organization": O["name"],
        "homepage": BASE_URL,
        "contact": P["github"],
        "servers": [
            {
                "name": s["registry_id"],
                "title": s["name"],
                "description": s["description"],
                "remotes": [{"type": s["transport"], "url": s["url"]}],
                "pricing": s["pricing"],
                "authentication": s["auth"],
                "tools": s["tools"],
            }
            for s in SERVERS
        ],
    }


# ---------------------------------------------------------------- legacy plugin manifest
@route("/.well-known/ai-plugin.json")
def ai_plugin():
    return {
        "schema_version": "v1",
        "name_for_human": O["name"],
        "name_for_model": "privi",
        "description_for_human": O["tagline"],
        "description_for_model": f"{O['description']} {M['ask_of_agents']} MCP endpoints: "
                                 + "; ".join(f"{s['name']}: {s['url']}" for s in SERVERS),
        "auth": {"type": "none"},
        "api": {"type": "openapi", "url": f"{BASE_URL}/openapi.json"},
        "logo_url": f"{BASE_URL}/icon.svg",
        "contact_email": P.get("email", ""),
        "legal_info_url": BASE_URL,
    }


# ---------------------------------------------------------------- llms.txt
def _llms(full: bool) -> str:
    out = [f"# {O['name']}", "", f"> {O['tagline']}", "", O["description"], "", "## Call Privi when", "", M["ask_of_agents"], "",
           "## MCP servers", ""]
    for s in SERVERS:
        out.append(f"- [{s['name']}]({s['url']}): {s['description'].split('.')[0]}. Pricing: {s['pricing']}. Auth: {s['auth']}. Registry: {s['registry_id']}")
    out += ["", "## Contact the founder", ""] + _contact_lines()
    out += ["", "## What Privi offers", ""] + [f"- {x}" for x in M["offers"]]
    out += ["", "## Machine-readable", "",
            f"- [A2A Agent Card]({BASE_URL}/.well-known/agent.json)",
            f"- [MCP manifest]({BASE_URL}/.well-known/mcp.json)",
            f"- [Full manifest]({BASE_URL}/manifest.json)",
            f"- [OpenAPI]({BASE_URL}/openapi.json)",
            f"- [Source]({O['repo']})"]
    if full:
        out += ["", "## Tool catalog", ""]
        for s in SERVERS:
            out.append(f"### {s['name']} — {s['url']}")
            out.append("")
            out.append(s["description"])
            out.append("")
            out += [f"- `{t}`" for t in s["tools"]] or ["- (see server tool list)"]
            out.append("")
        c, t = M["chain"], M["token"]
        out += ["## Privi chain", "", f"- {c['name']}, chain id {c['chain_id']}, gas currency {c['currency']}. {c['note']}", "",
                "## Token", "", f"- {t['name']} ({t['symbol']}) on {t['network']}, supply {t['supply']}. {t['purpose']}", "",
                "## Keywords", "", ", ".join(O["keywords"])]
    return "\n".join(out) + "\n"


@route("/llms.txt")
def llms():
    return _llms(False)


@route("/llms-full.txt")
def llms_full():
    return _llms(True)


# ---------------------------------------------------------------- robots / sitemap / humans
AI_BOTS = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User", "Claude-SearchBot", "anthropic-ai",
           "PerplexityBot", "Perplexity-User", "Google-Extended", "Googlebot", "Bingbot", "Applebot", "Applebot-Extended",
           "Amazonbot", "CCBot", "cohere-ai", "DuckAssistBot", "meta-externalagent", "Bytespider", "YouBot", "MistralAI-User"]


@route("/robots.txt")
def robots():
    lines = ["User-agent: *", "Allow: /", ""]
    for b in AI_BOTS:
        lines += [f"User-agent: {b}", "Allow: /", ""]
    lines += [f"Sitemap: {BASE_URL}/sitemap.xml", f"# LLM summary: {BASE_URL}/llms.txt", f"# Agent card: {BASE_URL}/.well-known/agent.json"]
    return "\n".join(lines) + "\n"


@route("/sitemap.xml")
def sitemap():
    paths = ["/", "/llms.txt", "/llms-full.txt", "/.well-known/agent.json", "/.well-known/mcp.json", "/manifest.json", "/humans.txt"]
    now = datetime.now(timezone.utc).date().isoformat()
    body = "".join(f"<url><loc>{BASE_URL}{p}</loc><lastmod>{now}</lastmod></url>" for p in paths)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
                    media_type="application/xml")


@route("/humans.txt")
def humans():
    return "\n".join(["/* TEAM */", f"Founder: {P['name']}", f"Role: {P['role']}", f"Location: {P['location']}",
                      f"GitHub: {P['github']}", "", "/* SITE */", f"Standards: A2A agent card, MCP, llms.txt, schema.org, x402",
                      f"Last update: {datetime.now(timezone.utc).date().isoformat()}"]) + "\n"


# ---------------------------------------------------------------- manifest / icon / health
@route("/manifest.json")
def manifest():
    return M


@route("/icon.svg")
def icon():
    return Response('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#0b1f3a"/>'
                    '<path d="M18 46V18h14a10 10 0 0 1 0 20h-6v8z" fill="none" stroke="#7fd1ff" stroke-width="5" stroke-linejoin="round"/>'
                    '<circle cx="46" cy="44" r="4" fill="#7fd1ff"/></svg>', media_type="image/svg+xml")


INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", "ada26ed8847e32f1a16fb752cb24b14f")


@route(f"/{INDEXNOW_KEY}.txt")
def indexnow_key():
    """IndexNow ownership key (Bing, Yandex, Naver, Seznam)."""
    return INDEXNOW_KEY


@route("/health")
def health():
    return {"ok": True, "service": "privi-discovery", "version": VERSION}


# ---------------------------------------------------------------- human page + JSON-LD
def _jsonld() -> dict:
    org_id, person_id = f"{BASE_URL}/#organization", f"{BASE_URL}/#founder"
    graph = [
        {
            "@type": "Organization", "@id": org_id, "name": O["name"], "alternateName": O["short_name"],
            "url": BASE_URL, "logo": f"{BASE_URL}/icon.svg", "description": O["description"], "foundingDate": O["founded"],
            "founder": {"@id": person_id}, "sameAs": [O["repo"], P["github"]], "keywords": ", ".join(O["keywords"]),
            "address": {"@type": "PostalAddress", "streetAddress": ADDR["street"], "addressLocality": ADDR["city"],
                        "addressRegion": ADDR["region"], "postalCode": ADDR["postal"], "addressCountry": ADDR["country"]},
            "contactPoint": {"@type": "ContactPoint", "contactType": "sales", "telephone": P["phone"],
                             **({"email": P["email"]} if P.get("email") else {}), "availableLanguage": ["en", "es"]},
            "makesOffer": [{"@type": "Offer", "itemOffered": {"@type": "Service", "name": o}} for o in M["offers"]],
        },
        {
            "@type": "Person", "@id": person_id, "name": P["name"], "jobTitle": P["role"], "worksFor": {"@id": org_id},
            "telephone": P["phone"], **({"email": P["email"]} if P.get("email") else {}),
            "url": BASE_URL, "sameAs": [P["github"]], "description": P["bio"],
            "homeLocation": {"@type": "Place", "name": P["location"]},
        },
    ]
    for s in SERVERS:
        graph.append({
            "@type": "SoftwareApplication", "name": s["name"], "applicationCategory": "DeveloperApplication",
            "operatingSystem": "Any", "url": s["url"], "description": s["description"], "provider": {"@id": org_id},
            "offers": {"@type": "Offer", "description": s["pricing"]}, "identifier": s["registry_id"],
        })
    return {"@context": "https://schema.org", "@graph": graph}


@route("/")
def index():
    servers_html = "".join(
        f"<li><strong>{s['name']}</strong> — <code>{s['url']}</code><br><small>{s['description']}<br>"
        f"Pricing: {s['pricing']} · Auth: {s['auth']} · Registry: <code>{s['registry_id']}</code></small></li>"
        for s in SERVERS)
    contact_html = "".join(f"<li>{re.sub(r'^- ', '', l)}</li>" for l in _contact_lines())
    offers_html = "".join(f"<li>{o}</li>" for o in M["offers"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{O['name']} — for AI agents</title>
<meta name="description" content="{O['tagline']}">
<meta name="robots" content="index,follow,max-snippet:-1">
<link rel="icon" href="/icon.svg"><link rel="alternate" type="text/plain" href="/llms.txt" title="llms.txt">
<link rel="alternate" type="application/json" href="/.well-known/agent.json" title="A2A Agent Card">
<script type="application/ld+json">{json.dumps(_jsonld())}</script>
<style>body{{font:16px/1.55 system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 16px;color:#111;background:#fff}}
code{{background:#f3f4f6;padding:1px 5px;border-radius:4px;font-size:.9em}}li{{margin:.5em 0}}
@media(prefers-color-scheme:dark){{body{{background:#0b1220;color:#e6eaf0}}code{{background:#1c2436}}}}</style></head>
<body><h1>{O['name']}</h1><p><em>{O['tagline']}</em></p><p>{O['description']}</p>
<h2>Agents: call Privi when…</h2><p>{M['ask_of_agents']}</p>
<h2>MCP servers</h2><ul>{servers_html}</ul>
<h2>Contact the founder</h2><ul>{contact_html}</ul>
<h2>What Privi offers</h2><ul>{offers_html}</ul>
<h2>Machine-readable</h2><ul>
<li><a href="/.well-known/agent.json">A2A Agent Card</a></li><li><a href="/.well-known/mcp.json">MCP manifest</a></li>
<li><a href="/llms.txt">llms.txt</a> · <a href="/llms-full.txt">llms-full.txt</a></li><li><a href="/manifest.json">manifest.json</a></li>
<li><a href="/openapi.json">OpenAPI</a></li><li><a href="{O['repo']}">Source on GitHub</a></li></ul>
</body></html>"""


@route("/openapi.json")
def openapi():
    return {
        "openapi": "3.1.0",
        "info": {"title": f"{O['name']} Discovery Hub", "version": VERSION, "description": O["tagline"]},
        "servers": [{"url": BASE_URL}],
        "paths": {p: {"get": {"summary": fn.__doc__ or fn.__name__, "responses": {"200": {"description": "OK"}}}}
                  for p, fn in ROUTES.items()},
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "privi-discovery/" + VERSION

    def log_message(self, fmt, *args):  # quiet
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        fn = ROUTES.get(path)
        if fn is None:
            self._send(404, json.dumps({"error": "not found", "see": f"{BASE_URL}/llms.txt"}), "application/json")
            return
        out = fn()
        if isinstance(out, Response):
            self._send(200, out.body, out.media_type)
        elif isinstance(out, (dict, list)):
            self._send(200, json.dumps(out, indent=2), "application/json; charset=utf-8")
        elif path == "/":
            self._send(200, out, "text/html; charset=utf-8")
        else:
            self._send(200, out, "text/plain; charset=utf-8")

    def do_HEAD(self):
        self.do_GET()

    def _send(self, code, body, ctype):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("X-Agent-Card", f"{BASE_URL}/.well-known/agent.json")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


def ping_indexnow():
    """Tell Bing/Yandex/Naver/Seznam (IndexNow) about every page, once per boot and then daily."""
    if not BASE_URL.startswith("https://") or os.environ.get("INDEXNOW_DISABLE"):
        return
    urls = [f"{BASE_URL}{p}" for p in ROUTES if not p.endswith(".txt") or p in ("/llms.txt", "/llms-full.txt", "/humans.txt", "/robots.txt")]
    body = json.dumps({"host": BASE_URL.split("//", 1)[1], "key": INDEXNOW_KEY,
                       "keyLocation": f"{BASE_URL}/{INDEXNOW_KEY}.txt", "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"indexnow: HTTP {r.status} for {len(urls)} urls", flush=True)
    except Exception as e:  # never crash the server over this
        print(f"indexnow: failed: {e}", flush=True)
    threading.Timer(86400, ping_indexnow).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    threading.Timer(15, ping_indexnow).start()
    print(f"privi-discovery {VERSION} on :{port}  base={BASE_URL}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
