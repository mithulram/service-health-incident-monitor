#!/bin/sh
set -e

cd /app
mkdir -p /app/data

echo "Running database migrations..."
alembic upgrade head

PORT="${PORT:-8090}"
echo "Starting API on 0.0.0.0:${PORT}..."
exec uvicorn service_monitor.app:app --host 0.0.0.0 --port "${PORT}"
