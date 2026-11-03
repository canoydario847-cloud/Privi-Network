#!/usr/bin/env python3
"""Render one to four reviewed SSH-only valueless Privi staging host files.

LOCAL filesystem ONLY. No Contabo API, no SSH, no cloud provisioning,
no blockchain, no production genesis, no keys generated and no PRVI.
"""
import argparse
import base64
import binascii
import os
from pathlib import Path
import re
import struct

KEY_MARKER = "REPLACE_WITH_REAL_SSH_ED25519_PUBLIC_KEY"
HOST_MARKER = "REPLACE_WITH_HOSTNAME"
BASE_DIR = Path(__file__).resolve().parent
KEY_PATTERN = re.compile(r"^ssh-ed25519 ([A-Za-z0-9+/]+={0,2})(?: ([A-Za-z0-9_.@-]{1,80}))?$")

def validate_public_key(text: str) -> str:
    """Accept exactly one normal ed25519 SSH PUBLIC key, no shell/YAML injection."""
    if not isinstance(text, str) or len(text) > 1024 or "\r" in text or "\n" in text.strip():
        raise ValueError("expected exactly one public SSH key line")
    text = text.strip()
    match = KEY_PATTERN.fullmatch(text)
    if not match:
        raise ValueError("expected one ssh-ed25519 PUBLIC key (never a private key)")
    try:
        blob = base64.b64decode(match.group(1), validate=True)
        if base64.b64encode(blob).decode("ascii") != match.group(1):
            raise ValueError("SSH key has noncanonical base64")
    except (binascii.Error, ValueError) as exc:
        raise ValueError("malformed SSH ed25519 public key data") from exc
    if len(blob) != 51:
        raise ValueError("unexpected SSH ed25519 key blob length")
    algorithm_length = struct.unpack(">I", blob[:4])[0]
    if algorithm_length != 11 or blob[4:15] != b"ssh-ed25519":
        raise ValueError("invalid ed25519 algorithm inside SSH key")
    key_length = struct.unpack(">I", blob[15:19])[0]
    if key_length != 32 or len(blob[19:]) != key_length:
        raise ValueError("invalid SSH ed25519 public key bytes")
    return "ssh-ed25519 " + match.group(1)

def render(template: str, key: str, index: int) -> str:
    if not isinstance(index, int) or not 1 <= index <= 4:
        raise ValueError("staging host index must be 1..4")
    if template.count(KEY_MARKER) != 1 or template.count(HOST_MARKER) != 1:
        raise ValueError("reviewed cloud-init template markers missing/duplicated")
    if not template.startswith("#cloud-config\n"):
        raise ValueError("template is not a cloud-init configuration")
    if "financial_mainnet_enabled: true" in template.lower() or "runcmd:" in template:
        raise ValueError("unsafe auto-run or financial mainnet template")
    return template.replace(KEY_MARKER, validate_public_key(key)).replace(
        HOST_MARKER, f"privi-stage-{index:02d}"
    )

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-public-key-file", required=True, type=Path,
                        help="local SSH .pub file only; NEVER provide a private key")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--count", type=int, choices=(1, 2, 3, 4), default=1)
    args = parser.parse_args()
    if not args.ssh_public_key_file.name.endswith(".pub"):
        parser.error("SSH key file must end in .pub; private key files are forbidden")
    try:
        if args.ssh_public_key_file.is_symlink():
            raise ValueError("refusing symlink public-key input")
        if args.ssh_public_key_file.stat().st_size > 1024:
            raise ValueError("SSH public-key file too large")
        key = validate_public_key(args.ssh_public_key_file.read_text(encoding="utf-8"))
        template = (BASE_DIR / "cloud-init.template.yaml").read_text(encoding="utf-8")
        rendered = [render(template, key, index) for index in range(1, args.count + 1)]
        dest = args.output_dir
        if dest.is_symlink():
            raise ValueError("refusing symlink output directory")
        dest.mkdir(mode=0o700, parents=True, exist_ok=True)
        outputs = [dest / f"privi-stage-{index:02d}.cloud-init.yaml" for index in range(1, args.count + 1)]
        if any(out.exists() or out.is_symlink() for out in outputs):
            raise ValueError("refusing to overwrite existing cloud-init output")
        created = []
        try:
            for out, contents in zip(outputs, rendered):
                fd = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                created.append(out)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(contents)
        except Exception:
            for out in created:
                out.unlink(missing_ok=True)
            raise
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Rendered {args.count} valueless, SSH-only staging cloud-init file(s) to {dest}.")
    print("NO CLOUD REQUESTS; NO PRVI ISSUANCE; NO FINANCIAL MAINNET.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
