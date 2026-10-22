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
with open("bnb-priv-readonly-check.json","w") as f:json.dump(d,f,indent=2)
print("PRIV_BNB_VERIFICATION",json.dumps(d))
if not d["verified"]:raise SystemExit(1)
