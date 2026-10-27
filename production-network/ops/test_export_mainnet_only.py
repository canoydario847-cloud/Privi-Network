"""Regression checks for the mainnet-only source export."""
import importlib.util
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
    subprocess.run(["git", "-C", str(repo), "add", "-f", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    output = tmp_path / "mainnet.tar"
    result = subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                            cwd=repo, capture_output=True, text=True)
    assert result.returncode != 0
    assert not output.exists()
