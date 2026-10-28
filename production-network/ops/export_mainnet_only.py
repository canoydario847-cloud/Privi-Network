#!/usr/bin/env python3
"""Stage a mainnet-only source export; never deploy or copy credentials."""
import argparse
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile

ALLOWED = ("production-network/mainnet", "production-network/ops")
EXCLUDED = ("life-ai-studio", "listing", "migration", "testnet")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Existing local Git commit/ref")
    parser.add_argument("--output", required=True, help="Output .tar archive path")
    args = parser.parse_args()
    output = pathlib.Path(args.output).resolve()
    if output.suffix != ".tar":
        parser.error("output must end in .tar")
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          check=True, capture_output=True, text=True).stdout.strip()
    commit = subprocess.run(["git", "-C", root, "rev-parse", "--verify", args.ref + "^{commit}"],
                            check=True, capture_output=True, text=True).stdout.strip()
    # Never publish a partially written archive, including if git archive
    # rejects a missing pathspec or raises after streaming some bytes.
    if output.exists() or output.is_symlink():
        raise RuntimeError("Refusing to overwrite an existing export")
    fd, temporary = tempfile.mkstemp(
        prefix=".privi-mainnet-export-", suffix=".tar", dir=output.parent
    )
    staging = pathlib.Path(temporary)
    try:
        with os.fdopen(fd, "wb") as target:
            subprocess.run(
                ["git", "-C", root, "archive", "--format=tar", commit, "--", *ALLOWED],
                check=True, stdout=target,
            )
        with tarfile.open(staging) as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if not names:
                raise RuntimeError("Unexpected empty archive")
            if any(
                not (name.rstrip("/") == "production-network" and member.isdir())
                and not any(name.rstrip("/") == p or name.startswith(p + "/") for p in ALLOWED)
                for name, member in zip(names, members)
            ):
                raise RuntimeError("Export contained a path outside the mainnet allowlist")
            if any(
                member.issym() or member.islnk() or not (member.isfile() or member.isdir())
                for member in members
            ):
                raise RuntimeError("Export contained an unsupported link or special file")
            if any(
                part.startswith(".env") or part in ("id_rsa", "id_ed25519")
                for name in names for part in pathlib.PurePosixPath(name).parts
            ):
                raise RuntimeError("Export contained a possible secret file")
        # Hard-link requires a nonexistent destination. Unlike os.replace, it
        # cannot silently overwrite a file another process just created.
        os.link(staging, output)
    finally:
        staging.unlink(missing_ok=True)
    print(f"Staged mainnet-only archive from {commit}: {output}")
    print("This is NOT a new GitHub repository, production binary, or mainnet launch.")

if __name__ == "__main__":
    main()
