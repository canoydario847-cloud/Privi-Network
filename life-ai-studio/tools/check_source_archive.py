"""Fail closed if a LIFE CI source ZIP includes private data or credentials.

This guards the downloadable *source artifact*, not staging storage, backups,
secret scanning of source code, or production release readiness.
"""
import argparse
import stat
import zipfile
from pathlib import PurePosixPath


_PRIVATE_SUFFIXES = (
    ".sqlite", ".sqlite3", ".db", ".sqlite-wal", ".sqlite-shm",
    ".sqlite3-wal", ".sqlite3-shm", ".db-wal", ".db-shm",
    ".db-journal", ".pem", ".key", ".p12", ".pfx", ".jks",
)
_PRIVATE_NAMES = {
    "id_rsa", "id_ed25519", "credentials.json", "secrets.json",
    ".npmrc", ".pypirc", ".netrc",
}


def validate_archive(path):
    """Check every archive member without extracting potentially private files."""
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not members:
            raise ValueError("Source archive is empty")
        seen = set()
        for member in members:
            raw = member.filename
            parts = PurePosixPath(raw).parts
            if (raw.startswith("/") or "\\" in raw or ".." in parts
                    or not parts or parts[0] != "life-ai-studio"
                    or (len(parts) < 2 and not (raw == "life-ai-studio/" and member.is_dir()))):
                raise ValueError("Source archive contains an unsafe path")
            normalized = raw.rstrip("/").casefold()
            if normalized in seen:
                raise ValueError("Source archive contains duplicate paths")
            seen.add(normalized)
            lower = [part.casefold() for part in parts]
            if ((len(lower) > 1 and "data" == lower[1]) or ".git" in lower
                    or any(part == ".env" or (part.startswith(".env.") and part != ".env.example")
                           for part in lower)
                    or any(part in _PRIVATE_NAMES for part in lower)
                    or lower[-1].endswith(_PRIVATE_SUFFIXES)):
                raise ValueError("Source archive contains a forbidden private file")
            mode = member.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or member.flag_bits & 1:
                raise ValueError("Source archive contains an unsafe file type")
        return len(members)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", help="ZIP file to validate before artifact upload")
    args = parser.parse_args()
    try:
        count = validate_archive(args.archive)
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        parser.exit(1, f"LIFE source artifact rejected: {exc}\n")
    print(f"LIFE source artifact checked: {count} entries; staging/payment gates unchanged")


if __name__ == "__main__":
    main()
