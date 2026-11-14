FROM python:3.13-slim
WORKDIR /app
COPY server.py /app/server.py
ENV PORT=10000 PRIVI_CHEM_DB_PATH=/data/privi-chem.sqlite3
RUN mkdir -p /data
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=4s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:10000/health',timeout=3)"
CMD ["python","server.py"]
