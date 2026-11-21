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


def test_reviewer_cli_defaults_closed(tmp_path,capsys):
    from privi_quantum.audit_cli import main
    dest=tmp_path/"review"
    generate(dest)
    args=["--bundle",str(dest/"certificate.json"),"--pins",str(dest/"test_pins.json"),
          "--hardware",str(dest/"hardware_receipt.json"),"--readback",str(dest/"readback.json"),
          "--binding",str(dest/"binding.json"),"--qasm",str(dest/"compiled.qasm")]
    assert main(args)==1
    capsys.readouterr()
    assert main(args+["--synthetic-demo"])==0
    result=json.loads(capsys.readouterr().out)
    assert result["synthetic_demo"] is True
    assert result["issuer_key_independently_trusted"] is False
    args[5]=str(dest/"tampered_receipt.json")
    assert main(args+["--synthetic-demo"])==1
