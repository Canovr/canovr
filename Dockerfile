FROM python:3.10-slim

WORKDIR /app

# System-Dependencies für NumPy/Numba (PyReason)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt 'setuptools<81'

COPY app/ app/

# PyReason JIT-Cache beim Build vorwärmen (echter Inference-Run)
RUN python -c "\
from app.reasoner import run_inference; \
from app.models import AthleteInput; \
a = AthleteInput(target_distance='10k', race_time_seconds=2700, weekly_km=30, experience_years=3, current_phase='general', days_since_hard_workout=99); \
run_inference(a); \
print('PyReason JIT cache warmed up') \
" && echo "=== CACHE FILES ===" \
  && find /usr/local/lib/python3.10/site-packages/pyreason/cache -type f 2>/dev/null | head -20 \
  && find /usr/local/lib/python3.10/site-packages/numba -name "*.nbi" -type f 2>/dev/null | head -5 \
  && echo "=== NUMBA_CACHE_DIR ===" \
  && python -c "import pyreason; import os; print(os.environ.get('NUMBA_CACHE_DIR', 'NOT SET'))"

# SQLite-DB
RUN mkdir -p /app/data
ENV CANOVR_DB_PATH=/app/data/canovr.db

EXPOSE 8080

CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
