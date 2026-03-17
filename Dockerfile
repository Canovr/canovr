FROM python:3.10-slim

WORKDIR /app

# System-Dependencies für NumPy/Numba (PyReason)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt 'setuptools<81'

# PyReason JIT-Cache beim Build vorwärmen
RUN python -c "import pyreason" 2>/dev/null || true

COPY app/ app/

# SQLite-DB im Volume
VOLUME /app/data
ENV CANOVR_DB_PATH=/app/data/canovr.db

EXPOSE 8080

CMD sh -c "litestar --app app.main:app run --host 0.0.0.0 --port ${PORT:-8000}"
