# Backend image. Build from the REPO ROOT (context = .) because the API imports
# both the backend app and the ml/ + pipeline/ packages.
#   docker build -f backend/Dockerfile -t pitchprophet-api .
FROM python:3.12-slim

WORKDIR /app

# System deps kept minimal; psycopg2-binary bundles libpq.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend:/app \
    PORT=8000

# Install Python deps first for layer caching.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/backend/requirements.txt

# App code.
COPY backend /app/backend
COPY ml /app/ml
COPY pipeline /app/pipeline

EXPOSE 8000

# Default command runs the API. The cron service overrides this to run the
# pipeline (see render.yaml). Uses $PORT so the host platform can assign it.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
