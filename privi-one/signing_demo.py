"""Generate and verify disposable Ed25519 signatures for SYNTHETIC Privi ONE.

No private signing key is persisted: one-shot generation emits a signed demo
receipt and a separate public verification-key file. Those two artifacts must
be pinned through a trusted channel before verification means anything.
Not a production trust anchor, external action proof, or blockchain record.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, HERE / path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load " + name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sig = load("signed_receipt.py", "privi_one_signed_receipt")
demo = load("demo.py", "privi_one_demo")


def generate(artifact_path, trusted_key_path):
    if artifact_path.resolve() == trusted_key_path.resolve():
        raise ValueError("Artifact and verification-key paths must differ")
    private, public = sig.create_keypair()
    # The user's private key never enters these files or a repository.
    mock = demo.evaluate("Summarize a synthetic non-sensitive report",
                         tool="report_summary", allowed_tools=["report_summary"],
                         budget_cents=10, approved=True,
                         secret=b"offline-demo-only-key-with-32-plus-bytes")
    signed = sig.sign_receipt(mock["receipt"], private_key_bytes=private)
    kid = sig.key_id(public)
    artifact_path.write_text(json.dumps(signed, indent=2) + "\n", encoding="utf-8")
    trusted_key_path.write_text(json.dumps(
        {"key_id": kid, "public_key_b64url": sig.b64(public),
         "key_source": "TEMPORARY_OFFLINE_DEMO_NOT_PRODUCTION_TRUST_ANCHOR"}, indent=2) + "\n",
        encoding="utf-8")
    return kid


def verify(artifact_path, trusted_key_path):
    signed = json.loads(artifact_path.read_text(encoding="utf-8"))
    keyinfo = json.loads(trusted_key_path.read_text(encoding="utf-8"))
    if (not isinstance(keyinfo, dict) or not isinstance(keyinfo.get("key_id"), str)
            or not isinstance(keyinfo.get("public_key_b64url"), str)):
        return False
    public = sig.unb64(keyinfo["public_key_b64url"])
    return sig.verify_receipt(signed, trusted_keys={keyinfo["key_id"]: public})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--trusted-key", required=True, type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        good = verify(args.artifact, args.trusted_key)
        print(json.dumps({"signature_verified": good, "mode": "LOCAL_SYNTHETIC_OFFLINE"}))
        return 0 if good else 2
    kid = generate(args.artifact, args.trusted_key)
    print(json.dumps({"written": True, "key_id": kid,
                      "warning": "Ephemeral test key only; not a Privi Ledger signature"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
