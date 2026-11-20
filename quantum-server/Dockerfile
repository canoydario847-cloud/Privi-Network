FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
# Evidence Lab regression: refuse an image whose QAOA->OpenQASM export is not equivalent.
# Exact classical statevector only; does not contact Qiskit Runtime or paid QPUs.
RUN python -c "from privi_quantum.qaoa import Qubo; from privi_quantum.evidence_lab import evaluate; r=evaluate(Qubo([[1.0,-0.4],[-0.4,-0.7]]),[0.7],[0.5]); assert r['verification']['passed'], 'QAOA/QASM evidence failed'"
# Hardware provenance smoke test: bounded synthetic measurements only, no provider calls.
RUN python -c "from privi_quantum.qaoa import Qubo,to_qasm; from privi_quantum.hardware_evidence import make_hardware_evidence; q=Qubo([[1.0,-0.4],[-0.4,-0.7]]); c=q.all_costs(); p=to_qasm(q,[0.7],[0.5],float(c.min()),float(c.max()-c.min())); r=make_hardware_evidence(qubo=q,gammas=[0.7],betas=[0.5],source_qasm=p,compiled_qasm=p,counts={'00':5,'01':5},provider='synthetic',backend='simulator',provider_job_id='fixture',submitted_utc='2026-11-20T00:00:00Z',completed_utc='2026-11-20T00:00:01Z',shots=10); assert r['checks']['compiled_distribution_equivalent'] and not r['physical_qpu_execution_verified']"
# IBM Quantum + Amazon Braket clients; IonQ needs nothing extra. A failure here never blocks the deploy.
RUN pip install --no-cache-dir ".[hardware]" || echo "hardware extra not installed; IonQ and local still work"

ENV PORT=8000 QUANTUM_DB_PATH=/data/quantum.db
RUN mkdir -p /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"

CMD ["privi-quantum-mcp"]
