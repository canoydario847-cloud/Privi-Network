"""Read-only BNB PRIV contract report. Copyright (c) 2026 Privi World Co."""
import hashlib,json,urllib.request,datetime
ADDRESS="0xbf154Ff2577F4B85db7B2ee910Db5880D06e0f64"
URLS=["https://bsc-dataseed.bnbchain.org","https://bsc-dataseed-public.bnbchain.org","https://bsc-rpc.publicnode.com"]
def query(url,method,args):
    req=urllib.request.Request(url,json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":args}).encode(),
       {"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=12) as res:r=json.loads(res.read())
    if "result" not in r:raise RuntimeError(str(r.get("error","missing result"))[:150])
    return r["result"]
d={"checked_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"contract":ADDRESS,
  "verified":False,"liquidity_verified":False,"market_price_verified":False,"merchant_wallet_verified":False,"errors":[]}
for url in URLS:
    try:
        if int(query(url,"eth_chainId",[]),16)!=56:raise RuntimeError("Wrong chain")
        code=query(url,"eth_getCode",[ADDRESS,"latest"])
        if not code or code=="0x":raise RuntimeError("No contract runtime code")
        raw=bytes.fromhex(code[2:])
        dec=int(query(url,"eth_call",[{"to":ADDRESS,"data":"0x313ce567"},"latest"]),16)
        if not 0<=dec<=36:raise RuntimeError("Invalid token decimals")
        try:
            sym=query(url,"eth_call",[{"to":ADDRESS,"data":"0x95d89b41"},"latest"])
            payload=bytes.fromhex(sym[2:])
            symbol=(payload[64:64+int.from_bytes(payload[32:64],"big")].decode(errors="replace")
                    if len(payload)>=64 else payload.rstrip(b"\\x00").decode(errors="replace"))
        except Exception:symbol=None
        d.update({"verified":True,"rpc":url,"chain_id":56,"runtime_code_sha256":hashlib.sha256(raw).hexdigest(),
                  "bytecode_size":len(raw),"decimals":dec,"contract_symbol_reported":symbol})
        break
    except Exception as e:d["errors"].append({"rpc":url,"error":str(e)[:160]})

# Optional DEX-pool discovery: no listing, price, or liquidity is assumed.
# This market snapshot is informational, not a promise of execution.
try:
    market_url="https://api.dexscreener.com/latest/dex/tokens/"+ADDRESS
    req=urllib.request.Request(market_url,headers={"User-Agent":"Privi-ReadOnly-Liquidity-Check/1.0"})
    with urllib.request.urlopen(req,timeout=12) as response:
        market=json.loads(response.read(400000))
    pairs=[p for p in (market.get("pairs") or []) if p.get("chainId")=="bsc"
           and ADDRESS.lower() in (p.get("baseToken",{}).get("address","").lower(),
                                    p.get("quoteToken",{}).get("address","").lower())]
    d["dex_pools_observed"]=len(pairs)
    if pairs:
        pairs.sort(key=lambda x:float((x.get("liquidity") or {}).get("usd") or 0),reverse=True)
        top=pairs[0]
        d["market_data_source"]="DexScreener public API at time checked"
        d["top_pool"]={"dex":top.get("dexId"),"pair_address":top.get("pairAddress"),
                       "liquidity_usd_estimate":(top.get("liquidity") or {}).get("usd"),
                       "price_usd_estimate":top.get("priceUsd"),
                       "token_base_address":(top.get("baseToken") or {}).get("address")}
        d["liquidity_verified"]=float((top.get("liquidity") or {}).get("usd") or 0)>0
        d["market_price_verified"]=bool(top.get("priceUsd"))
except Exception as exc:
    d["dex_lookup_error"]=type(exc).__name__+": "+str(exc)[:120]

with open("bnb-priv-readonly-check.json","w") as f:json.dump(d,f,indent=2)
print("PRIV_BNB_VERIFICATION",json.dumps(d))
if not d["verified"]:raise SystemExit(1)
