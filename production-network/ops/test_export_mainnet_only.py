"""Regression checks for the mainnet-only source export."""
import unittest
import pathlib
import subprocess
import sys
import tarfile

SCRIPT = pathlib.Path(__file__).with_name("export_mainnet_only.py")


def test_mainnet_export_is_allowlisted(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "ci@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "CI"], check=True)
    for path in ("production-network/mainnet/chain.go",
                 "production-network/ops/launch.md",
                 "life-ai-studio/private.txt",
                 "production-network/listing/token.txt"):
        file = repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("synthetic fixture", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    output = tmp_path / "mainnet.tar"
    subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                   cwd=repo, check=True, capture_output=True, text=True)
    with tarfile.open(output) as archive:
        files = [m.name for m in archive.getmembers() if m.isfile()]
    assert "production-network/mainnet/chain.go" in files
    assert "production-network/ops/launch.md" in files
    assert "life-ai-studio/private.txt" not in files
    assert "production-network/listing/token.txt" not in files


def test_mainnet_export_rejects_secret_named_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "ci@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "CI"], check=True)
    file = repo / "production-network" / "mainnet" / ".env"
    file.parent.mkdir(parents=True)
    file.write_text("synthetic fixture")
    # Keep both allowlisted paths present so this actually exercises
    # secret-name detection, not merely git archive's missing-path failure.
    ops_file = repo / "production-network" / "ops" / "README.md"
    ops_file.parent.mkdir(parents=True)
    ops_file.write_text("review-only fixture", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-f", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    output = tmp_path / "mainnet.tar"
    result = subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                            cwd=repo, capture_output=True, text=True)
    assert result.returncode != 0
    assert not output.exists()

def test_archive_failure_leaves_no_partial_output(tmp_path):
    # Missing ops pathspec causes git archive to fail after the output temp
    # file was opened. No user-visible archive should survive.
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "ci@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "CI"], check=True)
    file = repo / "production-network" / "mainnet" / "only.txt"
    file.parent.mkdir(parents=True)
    file.write_text("fixture", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    output = tmp_path / "mainnet.tar"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=repo, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert not output.exists()
    assert not list(tmp_path.glob(".privi-mainnet-export-*"))


def test_existing_archive_never_overwritten(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "ci@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "CI"], check=True)
    for name in ("production-network/mainnet/source.txt", "production-network/ops/readme.txt"):
        file = repo / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("fixture", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    output = tmp_path / "mainnet.tar"
    output.write_bytes(b"preexisting archive must stay untouched")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=repo, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert output.read_bytes() == b"preexisting archive must stay untouched"

class ExportTests(unittest.TestCase):
    def test_mainnet_export_is_allowlisted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            test_mainnet_export_is_allowlisted(pathlib.Path(directory))

    def test_mainnet_export_rejects_secret_named_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            test_mainnet_export_rejects_secret_named_file(pathlib.Path(directory))

    def test_archive_failure_leaves_no_partial_output(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            test_archive_failure_leaves_no_partial_output(pathlib.Path(directory))

    def test_existing_archive_never_overwritten(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            test_existing_archive_never_overwritten(pathlib.Path(directory))

