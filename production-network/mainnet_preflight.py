#!/usr/bin/env python3
"""Read-only Privi financial mainnet launch readiness check. Never authorizes launch."""
import json, os, sys, urllib.request
REQUIRED = ["PRVI_GENESIS_SHA256","PRVI_CHAIN_ID","PRVI_BINARY_VERSION",
"PRVI_VALIDATOR_QUORUM_EVIDENCE","PRVI_INDEPENDENT_SECURITY_AUDIT",
"PRVI_BACKUP_RESTORE_TEST","PRVI_INCIDENT_RESPONSE_PLAN",
"PRVI_EXPLORER_URL","PRVI_PUBLIC_RPC_URL"]
def main():
    checks = {k: ("present" if os.environ.get(k, "").strip() else "missing") for k in REQUIRED}
    url = os.environ.get("PRVI_RPC_URL", "")
    rpc = {"status":"not_configured"}
    if url:
        if not url.startswith("https://"):
            rpc = {"status":"fail","reason":"HTTPS required"}
        else:
            try:
                with urllib.request.urlopen(url.rstrip("/")+"/status", timeout=6) as response:
                    result=json.load(response).get("result",{})
                sync=result.get("sync_info",{})
                rpc={"status":"pass" if sync.get("catching_up") is False else "fail",
                     "catching_up":sync.get("catching_up"),
                     "latest_block_height":sync.get("latest_block_height")}
            except Exception as exc:
                rpc={"status":"fail","reason":type(exc).__name__}
    ready=all(v=="present" for v in checks.values()) and rpc["status"]=="pass"
    print(json.dumps({"project":"Privi native financial mainnet",
                      "ready_for_review":ready,"launch_authorized":False,
                      "checks":checks,"rpc":rpc},indent=2))
    return 0 if ready else 1
if __name__=="__main__":
    sys.exit(main())
