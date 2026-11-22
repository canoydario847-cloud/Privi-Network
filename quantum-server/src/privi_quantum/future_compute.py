# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Commercial Future Compute product catalog, with honest access terms."""
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from html import escape

PRODUCTS = (
    ("optimizer", "Compute Optimizer", "Optimize bounded scheduling, resource allocation and binary decisions.", "quantum_optimize", "19.99"),
    ("shield", "Post-Quantum Shield", "Identify cryptographic migration priorities and generate a readiness assessment.", "pqc_readiness_package", "19.99"),
    ("vault", "Secure Data Vault", "Protect long-lived data using hybrid X25519 and ML-KEM encryption, locally where possible.", "vault_seal", "19.99"),
)

def catalog(pay):
    return {
        "product": "Privi Future Compute",
        "creator": "Dario Canoy",
        "execution": "classical and quantum-inspired software; no physical QPU required",
        "services": [{"id":i,"name":n,"description":d,"tool":t,
                      "proposed_package_usd":p,
                      "current_mcp_access":pay.price_table().get(t,"consult current tool pricing")}
                     for i,n,d,t,p in PRODUCTS],
        "proposed_pro_usd":"35.00",
        "automatic_package_checkout_available":False,
        "purchase_contact":"dariocanoy@priviflow.us",
        "physical_quantum_advantage_claimed":False,
    }

def render(pay):
    data=catalog(pay)
    cards="".join(
        '<article><span class="tag">'+escape(p["id"].upper())+'</span><h2>'+escape(p["name"])+'</h2><p>'+escape(p["description"])+'</p><p class="price">$'+escape(p["proposed_package_usd"])+' <small>proposed service package</small></p><p>Current API: '+escape(p["current_mcp_access"])+'</p><code>'+escape(p["tool"])+'</code><p><a class="button secondary" href="mailto:dariocanoy@priviflow.us?subject=Future%20Compute%20'+escape(p["id"])+'">Request purchase</a></p></article>'
        for p in data["services"])
    return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Privi Future Compute</title><style>
    *{box-sizing:border-box}body{margin:0;background:#080e19;color:#e6f1ff;font:16px/1.6 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:36px 24px}header{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}a{color:#7de4e0}h1{font-size:clamp(2.6rem,7vw,5rem);line-height:1.02;letter-spacing:-.05em;margin:60px 0 16px}h2{font-size:1.45rem;line-height:1.2}p{color:#b9c9dc}.lead{font-size:1.2rem;max-width:690px}.tag{font-size:.78rem;color:#7de4e0;letter-spacing:.14em}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin:36px 0}article,.pro{padding:24px;background:#101d30;border:1px solid #304761;border-radius:16px}.price{font-weight:700;font-size:1.55rem;color:white}.price small{font-size:.8rem;font-weight:400;color:#aebfd2}.button{display:inline-block;padding:12px 18px;background:#7de4e0;color:#081623;border-radius:8px;font-weight:700;text-decoration:none}.secondary{background:#20394c;color:#b2fff5}code{overflow-wrap:anywhere;color:#c8dcff}footer{border-top:1px solid #304761;margin-top:36px;padding:20px 0;color:#aebfd2;font-size:.85rem}
    </style></head><body><main><header><strong>PRIVI / FUTURE COMPUTE</strong><a href="/health">Service health</a></header><span class="tag">COMPUTE · SECURITY · VERIFIABLE RESULTS</span><h1>Compute smarter.<br>Protect tomorrow.</h1><p class="lead">Practical optimization and post-quantum security tools built for businesses and AI agents. Runs on today's computing infrastructure without requiring physical quantum hardware.</p><a class="button" href="#services">Explore services</a><div class="grid" id="services">"""+cards+"""</div><section class="pro"><span class="tag">FUTURE COMPUTE PRO</span><h2>Three services. One proposed package.</h2><p class="price">$35 <small>proposed one-time price</small></p><p>Request purchase and confirm service scope and access with Privi. Automatic package checkout is not currently available; no payment is collected on this page.</p><a class="button" href="mailto:dariocanoy@priviflow.us?subject=Privi%20Future%20Compute%20Pro">Request Pro access</a><p>Already using an MCP client? Connect to <code>/mcp</code> and follow its current payment requirements. <a href="/future-compute/catalog.json">Machine-readable catalog</a>.</p></section><footer>Made by Dario Canoy • Copyright 2026 Privi World Corp. No guaranteed savings, physical quantum advantage, or third-party endorsement claimed.</footer></main></body></html>"""

def register(mcp, pay):
    @mcp.custom_route("/future-compute", methods=["GET"], include_in_schema=False)
    async def future_compute(_: Request):
        return HTMLResponse(render(pay), headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"})

    @mcp.custom_route("/future-compute/catalog.json", methods=["GET"], include_in_schema=False)
    async def future_compute_catalog(_: Request):
        return JSONResponse(catalog(pay),headers={"Cache-Control":"no-store"})
