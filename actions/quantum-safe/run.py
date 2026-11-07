# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Privi Quantum-Safe Check: GitHub Action entry point.

Runs the Privi Quantum readiness scanner (quantum-server/src/privi_quantum/scanner.py, the same code the
Privi Quantum MCP server uses) inside the caller's CI. Nothing leaves the runner. Writes a job summary,
SARIF for code scanning and step outputs, and fails the job at the chosen severity.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
SCANNER = HERE.parent.parent / "quantum-server" / "src" / "privi_quantum" / "scanner.py"
PRIVI_URL = "https://privi-quantum.onrender.com"
LEVELS = {"CRITICAL": "error", "HIGH": "error", "MEDIUM": "warning", "INFO": "note"}
RANK = {"critical": 0, "high": 1, "medium": 2}
SEV_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 9}


def load_scanner():
    spec = importlib.util.spec_from_file_location("privi_scanner", SCANNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def badge(score: int) -> str:
    color = "brightgreen" if score >= 90 else "yellow" if score >= 60 else "red"
    return f"https://img.shields.io/badge/quantum--ready-{score}%2F100-{color}"


def to_sarif(scanner, report: dict) -> dict:
    rules = {}
    for rid, sev, _rx, why, fix in scanner.RULES:
        rules[rid] = {"id": rid, "name": rid, "shortDescription": {"text": why},
                      "help": {"text": fix}, "defaultConfiguration": {"level": LEVELS[sev]},
                      "properties": {"tags": ["security", "post-quantum", "cryptography"]}}
    results = []
    for f in report["findings"]:
        if f["severity"] == "INFO":
            continue
        results.append({
            "ruleId": f["rule"], "level": LEVELS[f["severity"]],
            "message": {"text": f"{f['why']}. Fix: {f['fix']}"},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": f["path"].replace(os.sep, "/")},
                                                "region": {"startLine": max(1, int(f["line"]))}}}],
        })
    return {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "Privi Quantum-Safe Check", "organization": "Privi World Co",
                                          "informationUri": PRIVI_URL, "rules": list(rules.values())}},
                      "results": results}]}


def summary(report: dict, show_info: bool) -> str:
    c, s = report["counts"], report["readiness_score"]
    lines = [f"## Privi Quantum-Safe Check", "", f"![quantum readiness]({badge(s)})", "",
             f"**Readiness score: {s}/100** · {report['files_scanned']} files scanned", "",
             "| Critical | High | Medium | Info |", "|---|---|---|---|",
             f"| {c['CRITICAL']} | {c['HIGH']} | {c['MEDIUM']} | {c['INFO']} |", ""]
    shown = [f for f in report["findings"] if show_info or f["severity"] != "INFO"][:50]
    if shown:
        lines += ["| Severity | Where | Why | Fix |", "|---|---|---|---|"]
        for f in shown:
            cell = lambda t: str(t).replace("|", "\\|")
            lines.append(f"| {f['severity']} | `{cell(f['path'])}:{f['line']}` | {cell(f['why'])} | {cell(f['fix'])} |")
        if len(report["findings"]) > len(shown):
            lines.append(f"\n…and more; see the SARIF file or the Security tab.")
    else:
        lines.append("No quantum-vulnerable patterns found (heuristic scan: a clean result means nothing obvious, not proven safe).")
    lines += ["", f"Get signed post-quantum readiness packages, live endpoint checks and quantum-safe agent identity "
              f"from [Privi Quantum]({PRIVI_URL}). Add the badge to your README: `![quantum readiness]({badge(s)})`"]
    return "\n".join(lines) + "\n"


def main() -> int:
    scanner = load_scanner()
    ws = Path(os.environ.get("GITHUB_WORKSPACE", "."))
    target = ws / os.environ.get("PRIVI_PATH", ".")
    if not target.exists():
        print(f"::error::Path not found: {target}")
        return 2
    report = scanner.scan(str(target))
    show_info = os.environ.get("PRIVI_SHOW_INFO", "false").lower() == "true"
    print(scanner.format_report(report, show_info=show_info))

    sarif_path = os.environ.get("PRIVI_SARIF", "privi-quantum.sarif").strip()
    if sarif_path:
        out = ws / sarif_path
        out.write_text(json.dumps(to_sarif(scanner, report), indent=2))
    for f in report["findings"]:
        if f["severity"] in ("CRITICAL", "HIGH"):
            print(f"::warning file={f['path']},line={f['line']},title=Quantum-vulnerable ({f['rule']})::{f['fix']}")

    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(summary(report, show_info))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"score={report['readiness_score']}\ncritical={report['counts']['CRITICAL']}\n"
                     f"high={report['counts']['HIGH']}\nsarif_file={sarif_path}\n")

    fail_on = os.environ.get("PRIVI_FAIL_ON", "critical").lower()
    if fail_on in RANK:
        worst = min((SEV_RANK[f["severity"]] for f in report["findings"]), default=9)
        if worst <= RANK[fail_on]:
            print(f"::error::Quantum-vulnerable cryptography at or above '{fail_on}' (score {report['readiness_score']}/100).")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
