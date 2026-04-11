FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8001
ENV LOG_LEVEL=INFO

EXPOSE 8001

CMD ["python", "server.py"]
