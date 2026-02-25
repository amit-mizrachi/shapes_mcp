FROM python:3.12-slim

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY mcp-server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/config.py ./config.py
COPY shared/ ./shared/
COPY mcp-server/src/ .

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 3001

CMD ["python", "server.py"]
