FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -r -u 10001 school
COPY school.py .
ENV PORT=8000 PYTHONDONTWRITEBYTECODE=1
USER school
EXPOSE 8000
CMD ["uvicorn", "school:app", "--host", "0.0.0.0", "--port", "8000"]
