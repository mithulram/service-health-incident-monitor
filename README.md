# Service Health & Incident Monitor

A runnable FastAPI service that models the operational concerns behind a cloud/platform role: health checks, Prometheus-compatible metrics, availability SLOs, error budgets, incidents, structured event logging, and a small dashboard backed by live API endpoints.

> **Scope note:** The service still exposes synthetic in-memory SLO/incident demo endpoints for portfolio compatibility. Milestone 1 adds persisted URL monitors, manual checks, and admin auth. Scheduled checks, status pages, and alerting are not implemented yet. This is early product foundation, not a full production monitoring platform.

![Operational dashboard preview](docs/screenshots/monitor-dashboard.png)

## What it demonstrates

- Persisted URL monitors stored in SQLite (Postgres-compatible schema via SQLAlchemy).
- Manual outbound HTTP checks with response-time recording and SSRF protections.
- Admin bearer-token auth for monitor management routes.
- FastAPI HTTP service design, typed request validation, and live API testing.
- Separate liveness (`/healthz`) and readiness (`/readyz`) endpoints.
- Availability SLO and **process-lifetime synthetic** error-budget calculation for a 99.5% target.
- Prometheus 0.0.4 text-format metrics at `/metrics`, with HELP/TYPE metadata and a valid text content type.
- Incident context alongside quantitative signals, including open and resolved incidents.
- A synthetic fault-injection endpoint used to prove that service errors consume the calculated error budget.
- A browser dashboard that fetches live service data, not a static mock-up.

## Run locally

Requirements: Python 3.11+.

```bash
git clone https://github.com/mithulram/service-health-incident-monitor.git
cd service-health-incident-monitor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
alembic upgrade head
DEMO_MODE=true uvicorn service_monitor.app:app --host 127.0.0.1 --port 8090
```

By default the service stores monitors in `./service_monitor.db`. Override with `DATABASE_URL`.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL (default `sqlite:///./service_monitor.db`) |
| `ADMIN_API_KEY` | Bearer token required for monitor CRUD and manual checks when set |
| `DEMO_MODE` | When `true`, allows protected routes without `ADMIN_API_KEY` for local/demo use |
| `WEB_CORS_ORIGINS` | Comma-separated exact browser origins |
| `CHECK_TIMEOUT_SECONDS` | Default timeout fallback (default `5`) |
| `MAX_MONITORS` | Maximum persisted monitors (default `25`) |

Visit [http://127.0.0.1:8090](http://127.0.0.1:8090) for the dashboard. API documentation is available at `/docs`.

### Monitor CRUD (demo/local)

With `DEMO_MODE=true`, protected routes are open locally. In non-demo mode, pass `Authorization: Bearer $ADMIN_API_KEY`.

```bash
curl -X POST http://127.0.0.1:8090/api/v1/monitors \
  -H 'Content-Type: application/json' \
  -d '{"name":"Example API","url":"https://example.com","method":"GET"}'

curl http://127.0.0.1:8090/api/v1/monitors

curl -X POST http://127.0.0.1:8090/api/v1/checks/run/1
```

Manual checks record a row in `check_results` and return status code, response time, and success/failure details.

**Coming later:** background scheduler, public status pages, and email alerting.

## Live demo

| Service | URL |
|---|---|
| Backend API | https://service-health-incident-monitor.onrender.com |
| Companion dashboard | https://operations-dashboard-b8v.pages.dev |

After deploying your own instance, verify with:

```bash
BACKEND_URL=https://service-health-incident-monitor.onrender.com python3 scripts/smoke_backend.py
BACKEND_URL=https://service-health-incident-monitor.onrender.com \
FRONTEND_ORIGIN=https://operations-dashboard-b8v.pages.dev \
ADMIN_API_KEY=your-render-secret \
python3 scripts/smoke_backend.py
```

## Endpoint contract

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Lightweight liveness signal |
| `GET /readyz` | Readiness signal |
| `GET /api/v1/summary` | Request counts, availability, SLO target, error budget, open-incident count |
| `GET /api/v1/slo` | SLO-focused summary |
| `GET /api/v1/incidents` | Synthetic incident context |
| `POST /api/v1/simulate/request` | Record a synthetic status code when `DEMO_MODE=true` (disabled otherwise) |
| `GET /metrics` | Prometheus text-format metrics |
| `GET /api/v1/monitors` | List persisted URL monitors (admin) |
| `POST /api/v1/monitors` | Create monitor (admin) |
| `GET /api/v1/monitors/{id}` | Get monitor (admin) |
| `PATCH /api/v1/monitors/{id}` | Update monitor (admin) |
| `DELETE /api/v1/monitors/{id}` | Delete monitor (admin) |
| `POST /api/v1/checks/run/{id}` | Run one manual check now (admin) |

## Operational model

The monitor starts with 399 successful responses and 1 server error: 99.75% availability. For a 99.5% SLO target, that leaves 50% of the **process-lifetime synthetic** error budget. Recording a `5xx` response through the simulation endpoint lowers availability and consumes more of that budget. The calculation covers the in-memory lifetime of the demo process, not a calendar month.

```bash
DEMO_MODE=true uvicorn service_monitor.app:app --host 127.0.0.1 --port 8090

curl -X POST http://127.0.0.1:8090/api/v1/simulate/request \
  -H 'Content-Type: application/json' \
  -d '{"status_code":503}'

curl http://127.0.0.1:8090/metrics
```

## Verify

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

The test suite checks health/readiness, SLO values, Prometheus response semantics, incident data, CORS behavior, and that an injected `503` reduces error-budget headroom.

### Deployed backend smoke test

After deploying, confirm the live API responds:

```bash
BACKEND_URL=https://your-service.onrender.com python3 scripts/smoke_backend.py
BACKEND_URL=https://your-service.onrender.com \
FRONTEND_ORIGIN=https://your-dashboard.pages.dev \
python3 scripts/smoke_backend.py
```

## Deploy for free (Render Web Service)

The public Render demo serves the portfolio **synthetic SLO/incident endpoints** (`/api/v1/summary`, `/api/v1/incidents`, `/metrics`). Milestone 1 also adds persisted URL monitors behind admin auth.

### Production-safe Render settings

| Variable | Recommended public Render value |
|---|---|
| `DEMO_MODE` | `false` (disables open monitor CRUD and `/api/v1/simulate/request`) |
| `ADMIN_API_KEY` | Strong random secret set only in Render dashboard/CLI (never commit) |
| `WEB_CORS_ORIGINS` | Exact frontend origin, e.g. `https://operations-dashboard-b8v.pages.dev` |
| `DATABASE_URL` | Optional. Default SQLite file is **ephemeral on Render free tier** (data lost on redeploy/restart). Acceptable for demo; use external Postgres later for durable monitors. |

Local development can keep `DEMO_MODE=true` for frictionless monitor CRUD without an admin key.

Recommended host: [Render](https://render.com) Free Web Service (Python native runtime).

| Setting | Value |
|---|---|
| Build command | `python -m pip install --upgrade pip && python -m pip install .` |
| Start command | `uvicorn service_monitor.app:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/healthz` |

A starter [`render.yaml`](render.yaml) Blueprint defaults to `DEMO_MODE=false` and prompts for secrets in the Render dashboard (`sync: false`).

**Deployment order with the companion dashboard:**

1. Deploy this backend and set `ADMIN_API_KEY`, `WEB_CORS_ORIGINS`, and `DEMO_MODE=false` in Render.
2. Deploy the [operations-dashboard](https://github.com/mithulram/operations-dashboard) frontend with `VITE_API_BASE_URL` pointing at this backend.
3. Run the smoke test below. Optionally pass `ADMIN_API_KEY` to verify protected monitor routes.

**Docker (optional):** The included `Dockerfile` binds to `0.0.0.0` and uses port `8090` locally or `$PORT` when set:

```bash
docker build -t service-monitor .
docker run --rm -p 8090:8090 -e DEMO_MODE=true service-monitor
```

**CORS:** Cross-origin browser access is limited to origins listed in `WEB_CORS_ORIGINS`. When unset, local dev defaults apply: `http://localhost:5173` and `http://127.0.0.1:5173`. Wildcard `*` is not used.

## Design boundaries

- Data is in-memory so a fresh clone runs immediately; a production implementation would source events from logs, traces, or a metrics backend.
- The metrics output follows Prometheus's human-readable text exposition style but does not replace a Prometheus server, alert manager, or dashboard platform.
- The `simulate` endpoint is intentionally a demo/testing hook and would not be publicly exposed in production.

## Resume-ready description

> Built a FastAPI service-health monitor that exposes readiness and Prometheus-format metrics, calculates a 99.5% availability SLO and error budget, correlates incidents with operational signals, and verifies fault-injection effects through HTTP tests.

## License

MIT. See [LICENSE](LICENSE).
