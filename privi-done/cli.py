"""Privi DONE command line: offline deployment review and human/agent code map.

Examples:
  python privi-done/cli.py deployment --intent intent.json --evidence evidence.json
  python privi-done/cli.py origin --source path/to/file.py
  python privi-done/cli.py origin --source path/to/file.py --manifest claims.json --trusted-fixture-keys keys.json

Never supply real signing keys in a CLI JSON file. The optional keys switch
is for throwaway LOCAL TEST fixtures only, and is not production attestation.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Privi DONE: offline outcome and code provenance preview")
    sub = parser.add_subparsers(dest="command", required=True)
    deployment = sub.add_parser("deployment", help="Assess a supplied deployment evidence snapshot")
    deployment.add_argument("--intent", required=True)
    deployment.add_argument("--evidence", required=True)
    origin_parser = sub.add_parser("origin", help="Show human/agent/unknown recorded source lines")
    origin_parser.add_argument("--source", required=True)
    origin_parser.add_argument("--manifest")
    origin_parser.add_argument("--trusted-fixture-keys",
                               help="TEST ONLY: JSON signer ID to 32+ byte hex key")
    github = sub.add_parser("github-checks", help="Read actual GitHub check-run reports; DOES NOT verify deployment")
    github.add_argument("--repository", required=True, help="owner/repo")
    github.add_argument("--commit", required=True, help="exact 40-character commit SHA")
    github.add_argument("--required", action="append", required=True,
                        help="required GitHub check name; repeat for multiple checks")
    render = sub.add_parser("render-deploy", help="Read Render deploy metadata (not health or completion proof)")
    render.add_argument("--service-id", required=True, help="Pinned Render service ID")
    render.add_argument("--repository", required=True, help="Expected GitHub owner/repo")
    render.add_argument("--commit", required=True, help="Expected full 40-character SHA")
    combined = sub.add_parser("provider-report", help="Correlate GitHub and Render metadata; still NOT an outcome certificate")
    combined.add_argument("--service-id", required=True)
    combined.add_argument("--repository", required=True)
    combined.add_argument("--commit", required=True)
    combined.add_argument("--required", action="append", required=True)
    combined.add_argument("--output", help="Optional local Markdown report path")
    args = parser.parse_args(argv)
    try:
        if args.command == "provider-report":
            github = load("github_checks").collect_checks(
                args.repository, args.commit, args.required)
            render = load("render_deploy").inspect_deployment(
                args.service_id, args.repository, args.commit)
            report_module = load("provider_report")
            result = report_module.assess_provider_reports(
                args.repository, args.commit, args.service_id, args.required,
                github, render)
            markdown = report_module.render_customer_markdown(result)
            if args.output:
                Path(args.output).write_text(markdown, encoding="utf-8")
            print(markdown)
            return 0 if result["status"] == "PROVIDER_REPORTS_MATCH_OUTCOME_PENDING" else 2
        if args.command == "render-deploy":
            report = load("render_deploy").inspect_deployment(
                args.service_id, args.repository, args.commit)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["reported_live_commit_matches"] else 2
        if args.command == "github-checks":
            report = load("github_checks").collect_checks(
                args.repository, args.commit, args.required)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["result"] == "REPORTED_CHECKS_SUCCESS_DEPLOYMENT_UNVERIFIED" else 2
        if args.command == "deployment":
            report = load("deployment_verifier").assess_deployment(
                read_json(args.intent), read_json(args.evidence))
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["result"].startswith("PASS_") else 2
        source = Path(args.source).read_text(encoding="utf-8")
        manifest = read_json(args.manifest) if args.manifest else None
        keys = read_json(args.trusted_fixture_keys) if args.trusted_fixture_keys else {}
        if not isinstance(keys, dict):
            raise ValueError("fixture key map must be an object")
        decoded = {name: bytes.fromhex(value) for name, value in keys.items()}
        report = load("code_origin").compare_code(source, manifest, pinned_keys=decoded)
        for item, line in zip(report["lines"], source.splitlines()):
            print("{:5d} {:7s} | {}".format(
                item["number"], item["category"].upper(), line))
        print(json.dumps({k: v for k, v in report.items() if k != "lines"},
                         indent=2, sort_keys=True))
        return 0
    except (ValueError, TypeError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print("Privi DONE error: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
