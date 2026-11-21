# Copyright (c) 2026 Privi World Corp.
# Made by Dario Canoy.
import json
from privi_quantum.audit_demo import generate
from privi_quantum.ibm_certificate import verify_readback_certificate

def test_demo_end_to_end(tmp_path):
    dest=tmp_path/"demo"
    report=generate(dest)
    assert report["classification"]=="SYNTHETIC_TEST_ONLY_NO_PROVIDER_CONNECTION"
    assert report["provider_authenticated"] is False
    assert report["expected_pass"]["valid"] is True
    assert report["expected_pass"]["issuer_key_independently_trusted"] is False
    assert report["expected_pass"]["synthetic_demo"] is True
    for key in ("production_rejection","tampered_receipt","wrong_key","tampered_qasm"):
        assert report[key]["valid"] is False
    bundle=json.loads((dest/"certificate.json").read_text())
    pins=json.loads((dest/"test_pins.json").read_text())
    assert bundle["certificate"]["body"]["synthetic_demo"] is True
    assert not verify_readback_certificate(bundle,pinned_issuer_keys=pins)["cryptographically_valid"]
    bundle["certificate"]["body"]["synthetic_demo"]=False
    assert not verify_readback_certificate(bundle,pinned_issuer_keys=pins,allow_synthetic_demo=True)["cryptographically_valid"]
    assert not list(dest.glob("*.sqlite"))
