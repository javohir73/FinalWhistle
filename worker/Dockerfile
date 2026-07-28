FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY . /app
ENV PYTHONPATH=/app/backend:/app
CMD ["python", "-m", "worker.main"]
