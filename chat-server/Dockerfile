FROM python:3.12-slim

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY chat-server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY chat-server/src/ ./chat-server/src/

USER appuser

ENV PYTHONPATH=/app

EXPOSE 3002

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "3002", "--app-dir", "/app/chat-server/src"]
