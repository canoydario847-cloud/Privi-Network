#!/usr/bin/env python3
"""Privi Cogvative Signature™ — retrospective Git line-provenance backfill.

© 2026 Privi World Co. This original scanner belongs to Privi World Co;
underlying files retain their own licenses and contributor rights.

Git author/time data are repository claims, not proof of AI authorship,
exclusive ownership, deployment expense, original creation time, or signatures.
Outputs source code HASHES and commit metadata, not source code plaintext.
"""
import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SECRET_FRAGMENTS = ("/.env", ".pem", ".p12", ".pfx", "private.key",
                    "credentials.json", "secret", "/.ssh/", "id_rsa")
COMMIT = re.compile(r"^([0-9a-f^]{40,41}) (\d+) (\d+)(?: (\d+))?$")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def cmd(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE).stdout


def content_lines(path):
    raw=path.read_bytes()
    if b"\0" in raw:
        return None
    try:
        raw.decode("utf-8")
    except UnicodeError:
        return None
    return raw.splitlines(keepends=True)


def blame(root,path,count):
    """Get Git-reported blame author, timestamp and commit for every current line."""
    result=cmd("git","blame","--line-porcelain","HEAD","--",path,cwd=root).decode(
        "utf-8", errors="replace").splitlines()
    records=[]
    commit=None
    author=None
    git_time=None
    for line in result:
        match=COMMIT.match(line)
        if match:
            commit=match.group(1)
            author=None
            git_time=None
        elif line.startswith("author "):
            author=line[7:]
        elif line.startswith("author-time "):
            try:
                git_time=datetime.fromtimestamp(int(line[12:]),timezone.utc).isoformat().replace("+00:00","Z")
            except (OverflowError,ValueError):
                git_time=None
        elif line.startswith("\t"):
            records.append({"git_commit":commit,"git_author_claim":author,
                            "git_author_time_utc_claim":git_time})
    if len(records)!=count:
        raise ValueError("Blame entries do not match byte-level line count")
    return records


def produce(root,output):
    root=root.resolve()
    filenames=cmd("git","ls-files","-z",cwd=root).split(b"\0")
    counts=Counter()
    current_revision=cmd("git","rev-parse","HEAD",cwd=root).decode().strip()
    with output.open("w",encoding="utf-8") as handle:
        header={"schema":"privi.cogvative.historical.v1",
                "backfilled_at_utc":datetime.now(timezone.utc).isoformat(),
                "source_revision":current_revision,
                "original_ai_agent_identity_verified":False,
                "original_prvi_deployment_cost_known":False,
                "signed_historical_records":False,
                "rights_notice":"© 2026 Privi World Co. Privi Cogvative Signature™; no claim to third-party source code"}
        handle.write(json.dumps({"manifest":header})+"\n")
        for name in filenames:
            if not name:
                continue
            try:
                rel=name.decode("utf-8")
                path=(root/rel).resolve()
                if not path.is_relative_to(root) or path.is_symlink():
                    counts["unsafe_or_link"]+=1
                    continue
                if any(marker in "/"+rel.lower() for marker in SECRET_FRAGMENTS):
                    counts["secret_filename_skipped"]+=1
                    continue
                if not path.is_file():
                    counts["not_a_file"]+=1
                    continue
                lines=content_lines(path)
                if lines is None:
                    counts["binary_or_non_utf8_skipped"]+=1
                    continue
                authors=blame(root,rel,len(lines)) if lines else []
                for index,(line,source) in enumerate(zip(lines,authors),1):
                    handle.write(json.dumps({
                        "path":rel,"line":index,
                        "source_line_sha256":sha(line),
                        "git":source,
                        "ai_agent_identity":"unknown_unverified",
                        "cogvative_issuer_signature":None,
                        "historical_prvi_deploy_gas_wei":None,
                        "ownership_verified":False
                    },ensure_ascii=False)+"\n")
                    counts["lines"]+=1
                counts["files"]+=1
            except Exception as exc:
                counts["unresolved_file"]+=1
                handle.write(json.dumps({"unresolved":rel,"reason":type(exc).__name__,
                                          "attribution":"unknown"})+"\n")
    return {"source_revision":current_revision,**counts}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",default=".")
    parser.add_argument("--output",default="cogvative-git-backfill.jsonl")
    args=parser.parse_args()
    summary=produce(Path(args.root),Path(args.output))
    Path(args.output+".summary.json").write_text(json.dumps(summary,indent=2))
    print("COGVATIVE_BACKFILL "+json.dumps(summary,sort_keys=True))


if __name__=="__main__":
    main()
