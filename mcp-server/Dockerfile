FROM python:3.12-slim

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .

RUN mkdir -p /app/db && chown -R appuser:appuser /app

USER appuser

EXPOSE 3001

CMD ["python", "server.py"]
