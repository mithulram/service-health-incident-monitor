FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --no-cache-dir .

EXPOSE 8090
CMD ["uvicorn", "service_monitor.app:app", "--host", "0.0.0.0", "--port", "8090"]
