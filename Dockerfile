ARG BASE_IMAGE=build-base

FROM python:3.10-slim AS build-base

WORKDIR /app

# System-Dependencies für NumPy/Numba (PyReason)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt 'setuptools<81'

# PyReason importieren um Basis-Cache zu erstellen
RUN python -c "import pyreason; print('PyReason imported')" 2>/dev/null || true

# SQLite-DB
RUN mkdir -p /app/data
ENV CANOVR_DB_PATH=/app/data/canovr.db

FROM ${BASE_IMAGE}

WORKDIR /app
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .

EXPOSE 8080

CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
