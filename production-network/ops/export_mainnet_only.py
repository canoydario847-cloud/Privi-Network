#!/usr/bin/env python3
"""Stage a mainnet-only source export; never deploy or copy credentials."""
import argparse
import pathlib
import subprocess
import sys

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
    # Export only allowlisted source and review material, from a pinned commit.
    # No .env, unrelated apps, exchange listings, migration or testnet content.
    with output.open("wb") as target:
        subprocess.run(["git", "-C", root, "archive", "--format=tar", commit, "--", *ALLOWED],
                       check=True, stdout=target)
    import tarfile
    with tarfile.open(output) as archive:
        names = archive.getnames()
        if not names:
            raise RuntimeError("Unexpected empty archive")
        if any(not any(name == p or name.startswith(p + "/") for p in ALLOWED) for name in names):
            output.unlink(missing_ok=True)
            raise RuntimeError("Export contained a path outside the mainnet allowlist")
    print(f"Staged mainnet-only archive from {commit}: {output}")
    print("This is NOT a new GitHub repository, production binary, or mainnet launch.")

if __name__ == "__main__":
    main()
