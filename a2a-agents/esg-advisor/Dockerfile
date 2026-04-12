FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8010
ENV LOG_LEVEL=INFO

EXPOSE 8010

CMD ["python", "server.py"]
