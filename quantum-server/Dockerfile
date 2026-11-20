FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
# Evidence Lab regression: refuse an image whose QAOA->OpenQASM export is not equivalent.
# Exact classical statevector only; does not contact Qiskit Runtime or paid QPUs.
RUN python -c "from privi_quantum.qaoa import Qubo; from privi_quantum.evidence_lab import evaluate; r=evaluate(Qubo([[1.0,-0.4],[-0.4,-0.7]]),[0.7],[0.5]); assert r['verification']['passed'], 'QAOA/QASM evidence failed'"
# IBM Quantum + Amazon Braket clients; IonQ needs nothing extra. A failure here never blocks the deploy.
RUN pip install --no-cache-dir ".[hardware]" || echo "hardware extra not installed; IonQ and local still work"

ENV PORT=8000 QUANTUM_DB_PATH=/data/quantum.db
RUN mkdir -p /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"

CMD ["privi-quantum-mcp"]
