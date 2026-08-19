FROM python:3.11-slim

WORKDIR /app

ENV DATA_SOURCE=parquet \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8048

# --preload загружает parquet и контуры один раз до форка воркеров.
# --timeout покрывает длинные запросы LiteLLM-прокси (LITELLM_TIMEOUT=120 по умолчанию).
CMD ["gunicorn", "app:server", \
     "--bind", "0.0.0.0:8048", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "180", \
     "--preload", \
     "--access-logfile", "-"]
