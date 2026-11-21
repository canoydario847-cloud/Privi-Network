# Copyright (c) 2026 Privi World Corp.
# Made by Dario Canoy.
"""Offline synthetic demonstration. All keys are disposable; no IBM connection.
Do not distribute the generated test certificate as evidence of provider activity.
"""
import argparse
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from qiskit import QuantumCircuit
from .attest import Attestor
from .qaoa import Qubo, to_qasm
from .hardware_evidence import make_hardware_evidence
from .ibm_readback import verify_ibm_readback
from .ibm_input_binding import bind_existing_ibm_job
from .ibm_certificate import issue_readback_certificate
from .offline_audit import audit_evidence_chain


def generate(output):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    q=Qubo([[1.,-.4],[-.4,-.7]])
    costs=q.all_costs()
    qasm=to_qasm(q,[.7],[.5],float(costs.min()),float(costs.max()-costs.min()))
    counts={"00":5,"01":7,"10":8}
    job_id="SYNTHETIC-DEMO-NOT-IBM"
    backend="synthetic_demo_backend"
    receipt=make_hardware_evidence(
        qubo=q,gammas=[.7],betas=[.5],source_qasm=qasm,compiled_qasm=qasm,
        counts=counts,provider="IBM-Quantum",backend=backend,provider_job_id=job_id,
        submitted_utc="2026-11-20T00:00:00Z",
        completed_utc="2026-11-20T00:00:01Z",shots=20)
    class FakeJob:
        program_id="sampler"
        inputs={"pubs":[(QuantumCircuit.from_qasm_str(qasm),)]}
        def job_id(self): return job_id
        def backend(self): return SimpleNamespace(name=backend)
        def status(self): return "DONE"
        def result(self):
            return [SimpleNamespace(data=SimpleNamespace(c=SimpleNamespace(
                get_counts=lambda:dict(counts))))]
    class FakeService:
        def job(self, requested):
            if requested!=job_id: raise ValueError("Unknown synthetic job")
            return FakeJob()
    service=FakeService()
    with TemporaryDirectory() as temp:
        signer=Attestor(str(Path(temp)/"disposable-demo.sqlite"))
        pins=signer.public_keys()
        bundle=issue_readback_certificate(receipt,compiled_qasm=qasm,
                                          service=service,attestor=signer)
        signer._db.close()
    rb=verify_ibm_readback(receipt,service=service)
    binding=bind_existing_ibm_job(receipt,compiled_qasm=qasm,service=service)
    args=dict(bundle=bundle,pinned_issuer_keys=pins,hardware_receipt=receipt,
              ibm_readback=rb,input_binding=binding,compiled_qasm=qasm)
    tampered=copy.deepcopy(receipt)
    tampered["shots"]=21
    report={
        "classification":"SYNTHETIC_TEST_ONLY_NO_PROVIDER_CONNECTION",
        "demo_keys_are_not_production_trust_roots":True,
        "provider_authenticated":False,
        "physical_qpu_execution_verified":False,
        "expected_pass":audit_evidence_chain(**args),
        "tampered_receipt":audit_evidence_chain(**dict(args,hardware_receipt=tampered)),
        "wrong_key":audit_evidence_chain(**dict(args,pinned_issuer_keys=None)),
        "tampered_qasm":audit_evidence_chain(**dict(args,compiled_qasm=qasm+"\n// alteration")),
    }
    # The underlying library assumes a trusted service; its success flags
    # in this fixture are simulated. Explicitly mark every exported container.
    files={"certificate.json":bundle,"test_pins.json":pins,
           "hardware_receipt.json":receipt,"readback.json":rb,
           "binding.json":binding,"tampered_receipt.json":tampered,
           "SYNTHETIC_REPORT.json":report}
    for name,obj in files.items():
        (output/name).write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n")
    (output/"compiled.qasm").write_text(qasm,encoding="utf-8")
    (output/"READ-ME-FIRST.txt").write_text(
        "SYNTHETIC TEST ONLY. No IBM account or QPU was contacted. "
        "All job records simulate provider responses. Keys are disposable test keys, "
        "not Privi production issuer keys. Do not use these files as real execution evidence.\n")
    if not report["expected_pass"]["valid"] or any(report[k]["valid"]
            for k in ("tampered_receipt","wrong_key","tampered_qasm")):
        raise RuntimeError("Synthetic audit regression failed")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("output",help="New directory for synthetic evidence files")
    args=p.parse_args()
    print(json.dumps(generate(args.output),indent=2))


if __name__=="__main__":
    main()
