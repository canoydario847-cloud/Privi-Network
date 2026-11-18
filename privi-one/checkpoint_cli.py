"""Sign a saved Privi ONE sandbox checkpoint offline, or verify its signature.

The auditor MUST obtain the checkpoint from /api/checkpoint and preserve the
trusted public key independently. Generating a one-off demo key is not production
key custody. This CLI never contacts Render or any blockchain.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load():
    spec = importlib.util.spec_from_file_location("privi_one_signed_checkpoint", HERE / "signed_checkpoint.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Checkpoint signer unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sign_saved(checkpoint_file, envelope_file, pinned_key_file):
    if len({Path(x).resolve() for x in (checkpoint_file, envelope_file, pinned_key_file)}) != 3:
        raise ValueError("Input, signature, and public key must use different files")
    s = load()
    checkpoint = read_json(checkpoint_file)
    private, public = s.generate_keypair()
    envelope = s.sign(checkpoint, private_key=private)
    kid = s.key_id(public)
    Path(envelope_file).write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    import base64
    Path(pinned_key_file).write_text(json.dumps({
        "key_id": kid,
        "public_key_b64url": base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii"),
        "trust": "DEMO_ONLY_MUST_PIN_INDEPENDENTLY",
    }, indent=2) + "\n", encoding="utf-8")
    return kid


def verify_saved(envelope_file, pinned_key_file):
    s = load()
    envelope = read_json(envelope_file)
    pinned = read_json(pinned_key_file)
    import base64
    try:
        pub64 = pinned["public_key_b64url"]
        public = base64.urlsafe_b64decode(pub64 + "=" * (-len(pub64) % 4))
        kid = pinned["key_id"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid trusted public-key file") from exc
    return s.verify(envelope, pinned_public_keys={kid: public})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--verify", action="store_true")
    p.add_argument("--checkpoint", help="existing /api/checkpoint JSON, required when signing")
    p.add_argument("--envelope", required=True)
    p.add_argument("--pinned-key", required=True)
    args = p.parse_args()
    if args.verify:
        valid = verify_saved(args.envelope, args.pinned_key)
        print(json.dumps({"signature_valid": valid, "mode": "OFFLINE_AUDITOR_ONLY"}))
        return 0 if valid else 2
    if not args.checkpoint:
        p.error("--checkpoint is required when signing")
    kid = sign_saved(args.checkpoint, args.envelope, args.pinned_key)
    print(json.dumps({"signature_created": True, "key_id": kid,
                      "warning": "one-time sandbox key; store public key independently"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
