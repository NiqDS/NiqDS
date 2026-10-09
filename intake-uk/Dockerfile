# Production image for the Intake Gate backend.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    INTAKE_DATA_DIR=/data

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Real LLM backends (needed to read photos/scans via vision). Build with
#   docker build --build-arg WITH_LLM=1 .
# to include them; leave unset for the offline mock-backend image.
ARG WITH_LLM=
RUN if [ -n "$WITH_LLM" ]; then pip install --no-cache-dir -r requirements-optional.txt; fi

# App code + the JSON fixtures the demo/mock backend needs (see .dockerignore).
COPY . .

# Persistent data (SQLite db, uploads, scans, session key) lives here — mount a
# volume at /data in production so it survives restarts/redeploys.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# Hosts that inject $PORT (Fly/Render/Railway/Lightsail) are honoured.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
