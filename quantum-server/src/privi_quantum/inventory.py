# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Crypto Inventory: point Privi Quantum at a company's public GitHub repositories and
domains and get one cryptographic bill of materials back.

Repositories are downloaded as a GitHub tarball and scanned in memory: nothing is written
to disk or kept after the scan, only regular text files are read, and only github.com
repositories are accepted (no other hosts, so the server can't be pointed at internal
addresses). Set GITHUB_TOKEN for higher GitHub rate limits or private repositories the
token can read.
"""
from __future__ import annotations

import io
import os
import re
import tarfile
import urllib.error
import urllib.parse
import urllib.request

from . import scanner

MAX_REPOS = 5
MAX_TARBALL = 40_000_000   # compressed bytes
MAX_FILES = 5_000
MAX_TEXT = 60_000_000      # total uncompressed bytes scanned per repo
_REPO = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?"
                   r"(?:/tree/([A-Za-z0-9._/-]{1,200}))?/?$")
_SHORT = re.compile(r"^([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100})$")


class InventoryError(ValueError):
    pass


def parse_repo(ref: str) -> tuple[str, str, str]:
    s = (ref or "").strip()
    m = _REPO.match(s) or _SHORT.match(s)
    if not m:
        raise InventoryError(f"not a GitHub repository: {s[:80]!r} (use https://github.com/owner/repo or owner/repo)")
    owner, repo = m.group(1), m.group(2)
    ref_ = m.group(3) if m.re is _REPO else None
    if repo in (".", ".."):
        raise InventoryError("bad repository name")
    return owner, repo, (ref_ or "")


def fetch_tarball(owner: str, repo: str, ref: str = "", opener=None, token: str | None = None) -> bytes:
    url = f"https://api.github.com/repos/{owner}/{repo}/tarball" + (f"/{ref}" if ref else "")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "privi-quantum-inventory"}
    tok = token if token is not None else os.getenv("GITHUB_TOKEN", "")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with (opener or urllib.request.urlopen)(req, timeout=60) as r:
            host = urllib.parse.urlparse(r.geturl()).hostname or ""
            if host not in ("api.github.com", "codeload.github.com"):
                raise InventoryError("GitHub redirected somewhere unexpected; refusing")
            buf = r.read(MAX_TARBALL + 1)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise InventoryError(f"{owner}/{repo} not found or not public") from e
        raise InventoryError(f"GitHub returned {e.code} for {owner}/{repo}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise InventoryError(f"could not reach GitHub: {e}") from e
    if len(buf) > MAX_TARBALL:
        raise InventoryError(f"{owner}/{repo} is larger than {MAX_TARBALL // 1_000_000} MB compressed; scan a smaller repo or send files")
    return buf


def scan_tarball(blob: bytes, label: str) -> dict:
    """Scan the text files in a GitHub tarball, in memory."""
    findings, files, total = [], 0, 0
    try:
        tf = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")
    except tarfile.TarError as e:
        raise InventoryError(f"not a valid archive: {e}") from e
    with tf:
        for m in tf:
            if files >= MAX_FILES or total >= MAX_TEXT:
                break
            if not m.isreg() or m.size > scanner.MAX_BYTES:
                continue
            parts = m.name.split("/")[1:]          # drop the owner-repo-sha/ prefix
            if not parts or any(p in scanner.SKIP_DIRS or p == ".." for p in parts[:-1]):
                continue
            name = parts[-1]
            ext = os.path.splitext(name)[1].lower()
            if ext not in scanner.TEXT_EXT and name not in ("Dockerfile", "sshd_config", "ssh_config"):
                continue
            f = tf.extractfile(m)
            if f is None:
                continue
            raw = f.read(scanner.MAX_BYTES + 1)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            files += 1
            total += len(raw)
            findings += scanner._scan_lines(text.splitlines(), "/".join(parts))
    rep = scanner._report(findings, files, label)
    rep["truncated"] = files >= MAX_FILES or total >= MAX_TEXT
    return rep


def scan_repo(ref: str, opener=None) -> dict:
    owner, repo, branch = parse_repo(ref)
    label = f"github.com/{owner}/{repo}" + (f"@{branch}" if branch else "")
    return scan_tarball(fetch_tarball(owner, repo, branch, opener), label)
