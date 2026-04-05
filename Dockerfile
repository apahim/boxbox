# Stage 1: Build dependencies
FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /tmp/requirements.txt

# Stage 2: Runtime
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -r -s /bin/false boxbox

COPY --from=builder /install /usr/local

WORKDIR /app

COPY app/ app/
COPY scripts/ scripts/
COPY migrations/ migrations/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENV FLASK_APP=app:create_app
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

USER boxbox

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "--graceful-timeout", "30", "app:create_app()"]
