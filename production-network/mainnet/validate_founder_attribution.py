#!/usr/bin/env python3
"""Static attribution-only validation. NEVER proves legal or wallet ownership.

This intentionally does not authorize a financial blockchain deployment.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
HEX_20_BYTES = re.compile(r"^0x[0-9a-fA-F]{40}$")


def validate_attribution(data):
    errors = []
    if not isinstance(data, dict):
        return ["Founder attribution must be an object"]
    org = data.get("organization") or {}
    founder = org.get("stated_owner_and_founder") or {}
    wallet = data.get("founder_wallet") or {}
    counsel = data.get("legal_review") or {}
    if data.get("schema_version") != 1:
        errors.append("Unrecognized founder attribution schema")
    if org.get("name") != "Privi World Corp." or founder.get("full_name") != "Dario Canoy":
        errors.append("Founder or company attribution differs from owner-supplied designation")
    if founder.get("public_title") != "Owner and Founder":
        errors.append("Public role must read Owner and Founder")
    if founder.get("attribution_basis") != "founder_self_declaration":
        errors.append("Unverified ownership claims must be marked self-declared")
    if founder.get("corporate_registry_verified") is not False:
        errors.append("Corporate ownership has not been independently established")
    if wallet.get("address_format") != "EVM_20_BYTE" or not isinstance(wallet.get("address"), str) \
            or not HEX_20_BYTES.fullmatch(wallet["address"]):
        errors.append("Founder wallet must be a syntactically valid 20-byte EVM address")
    if wallet.get("attributed_to") != founder.get("full_name") or \
            wallet.get("association_basis") != "previously_supplied_by_founder":
        errors.append("Founder wallet attribution basis is inconsistent")
    if wallet.get("cryptographic_control_proof_verified") is not False or \
            wallet.get("approved_for_financial_mainnet_genesis") is not False or \
            wallet.get("treasury_multisig_or_validator_key") is not False:
        errors.append("Founder wallet cannot silently become verified or funded mainnet authority")
    if counsel.get("firm_name_as_reported") != "Sigal Law" or \
            counsel.get("source") != "reported_by_founder" or \
            counsel.get("claimed_signoff") is not True:
        errors.append("Reported legal counsel statement is inconsistent")
    if counsel.get("status") != "REPORTED_SIGNOFF_DOCUMENTARY_VERIFICATION_PENDING" or \
            counsel.get("verified_signed_legal_opinion_sha256") is not None or \
            counsel.get("reviewer_identity_and_scope_verified") is not False or \
            counsel.get("independent_legal_release_gate_satisfied") is not False:
        errors.append("A reported counsel signoff alone cannot satisfy independent legal release approval")
    if data.get("financial_mainnet_activated") is not False:
        errors.append("Public attribution must not claim a live financial mainnet")
    return errors


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path,
                        default=HERE / "founder_attribution.json")
    a = parser.parse_args()
    try:
        doc = json.loads(a.file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    failures = validate_attribution(doc)
    if failures:
        for failure in failures:
            print("BLOCKED: " + failure)
        return 1
    print("Founder attribution metadata structurally consistent; neither corporate control nor legal signoff verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
