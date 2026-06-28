FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY scripts/docker-entrypoint.sh ./scripts/docker-entrypoint.sh

RUN python -m pip install --no-cache-dir . \
    && chmod +x scripts/docker-entrypoint.sh \
    && mkdir -p /app/data

ENV DATABASE_URL=sqlite:////app/data/service_monitor.db \
    DEMO_MODE=false \
    SCHEDULER_ENABLED=true \
    ALERTS_ENABLED=false

EXPOSE 8090

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
