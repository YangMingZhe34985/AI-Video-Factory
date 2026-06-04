#!/bin/bash
set -e

echo "============================================"
echo "  AI Video Factory — Backend Startup"
echo "============================================"

echo "[1/3] Running database migrations..."
flask --app run.py db upgrade
echo "      Migrations OK."

echo "[2/3] Seeding default data (idempotent)..."
flask --app run.py seed-defaults || true
echo "      Seed OK."

echo "[3/3] Starting Gunicorn..."
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers "${GUNICORN_WORKERS:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-300}" \
    --worker-class sync \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    "run:app"
