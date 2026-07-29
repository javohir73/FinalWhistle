FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
COPY worker/requirements.txt /app/worker/requirements.txt
RUN pip install --no-cache-dir -r /app/worker/requirements.txt
COPY . /app
ENV PYTHONPATH=/app/backend:/app
# Disabled unless MARKET_CAPTURE_ENABLED and MARKET_CAPTURE_MARKET_KEYS are set.
CMD ["python", "-m", "worker.main"]
