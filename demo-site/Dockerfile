FROM python:3.12-slim
WORKDIR /app
COPY index.html favicon.svg serve.py ./
COPY videos ./videos
ENV PORT=8080
CMD ["python", "serve.py"]
