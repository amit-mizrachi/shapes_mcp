FROM python:3.12-slim

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY mcp-server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY mcp-server/src/ ./mcp-server/src/

RUN mkdir -p /app/db && chown -R appuser:appuser /app

USER appuser

ENV PYTHONPATH=/app

EXPOSE 3001

CMD ["python", "/app/mcp-server/src/server.py"]
