# Reproducible, catalog-only Privi Network MCP server for Glama.
# The six separately deployed commercial services are NOT embedded or proxied.
FROM python:3.13-slim
WORKDIR /app
COPY glama-directory/ /app/glama-directory/
RUN python -m unittest discover -s /app/glama-directory -p 'test_*.py' -v \
    && python -m py_compile /app/glama-directory/server.py \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin privi
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
CMD ["python", "-u", "/app/glama-directory/server.py"]
