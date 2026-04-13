FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root for security (same pattern as backend Dockerfile)
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

ENV PORT=8002
ENV LOG_LEVEL=INFO

EXPOSE 8002

CMD ["python", "server.py"]
