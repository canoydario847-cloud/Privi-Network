"""Tests for the Privi Quantum-Safe Check action. Run: python3 -m pytest actions/quantum-safe"""
import json
import os
import subprocess
import sys
from pathlib import Path

RUN = Path(__file__).with_name("run.py")


def _run(ws: Path, fail_on: str, path: str = ".") -> tuple[int, dict]:
    out = ws / "out.txt"
    env = {**os.environ, "GITHUB_WORKSPACE": str(ws), "GITHUB_OUTPUT": str(out),
           "GITHUB_STEP_SUMMARY": str(ws / "sum.md"), "PRIVI_PATH": path, "PRIVI_FAIL_ON": fail_on}
    code = subprocess.run([sys.executable, str(RUN)], env=env, capture_output=True).returncode
    vals = dict(l.split("=", 1) for l in out.read_text().splitlines()) if out.exists() else {}
    return code, vals


def test_flags_rsa_and_writes_sarif(tmp_path):
    (tmp_path / "a.py").write_text("from x import rsa\nk = rsa.generate_private_key(public_exponent=65537, key_size=2048)\n")
    code, vals = _run(tmp_path, "high")
    assert code == 1 and int(vals["high"]) >= 1 and int(vals["score"]) < 100
    sarif = json.loads((tmp_path / "privi-quantum.sarif").read_text())
    res = sarif["runs"][0]["results"]
    assert res and all(r["level"] == "error" for r in res)
    assert 2 in [r["locations"][0]["physicalLocation"]["region"]["startLine"] for r in res]
    assert "quantum--ready" in (tmp_path / "sum.md").read_text()


def test_fail_threshold_and_clean(tmp_path):
    (tmp_path / "a.py").write_text("import hashlib\nhashlib.md5(b'x')\n")
    assert _run(tmp_path, "high")[0] == 0       # only MEDIUM present
    assert _run(tmp_path, "medium")[0] == 1
    assert _run(tmp_path, "none")[0] == 0


def test_missing_path(tmp_path):
    assert _run(tmp_path, "critical", "does-not-exist")[0] == 2
