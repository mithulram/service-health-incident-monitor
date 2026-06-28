# Service Health & Incident Monitor

A **free-first, self-hostable monitoring API** for solo developers, open-source maintainers, and small teams. Check HTTP endpoints on a schedule, open incidents automatically, send optional email alerts, and expose a public JSON status page for your users.

The companion [operations-dashboard](https://github.com/mithulram/operations-dashboard) frontend provides the product UI (monitors, incidents, alerts, public status pages). This backend is the API and scheduler.

## Live demo

| Service | URL |
|---|---|
| Backend API | https://service-health-incident-monitor.onrender.com |
| Dashboard UI | https://operations-dashboard-b8v.pages.dev |
| Public status page | https://operations-dashboard-b8v.pages.dev/status/default |

## Quick self-host (~10 minutes)

Requirements: [Docker](https://docs.docker.com/get-docker/) and Docker Compose.

```bash
git clone https://github.com/mithulram/service-health-incident-monitor.git
cd service-health-incident-monitor
cp .env.example .env
# Edit .env and set ADMIN_API_KEY to a long random secret
docker compose up -d --build
```

The API listens on [http://127.0.0.1:8090](http://127.0.0.1:8090). SQLite data persists in `./data`.

Verify the instance:

```bash
ADMIN_API_KEY=your-secret-from-env python3 scripts/smoke_self_host.py
```

Then run the [operations-dashboard](https://github.com/mithulram/operations-dashboard) locally with `VITE_API_BASE_URL=http://127.0.0.1:8090`, paste the same admin key in **Settings**, and manage monitors from the UI.

### What Docker Compose sets by default

| Setting | Self-host default | Why |
|---|---|---|
| `DEMO_MODE` | `false` | Protected routes require your admin key |
| `SCHEDULER_ENABLED` | `true` | Automatic interval checks on an always-on host |
| `ALERTS_ENABLED` | `false` | Opt in after SMTP env vars are configured |
| `DATABASE_URL` | `sqlite:////app/data/service_monitor.db` | Persisted under `./data` volume |
| `WEB_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Local dashboard dev server |

Migrations run automatically on container start (`alembic upgrade head`).

## Architecture

```mermaid
flowchart LR
  subgraph browser [Browser]
    UI[operations-dashboard]
    Public[/status/slug]
  end

  subgraph api [Monitor API]
    Monitors[URL monitors]
    Scheduler[Interval scheduler]
    Incidents[Auto incidents]
    Alerts[Email alerts]
    Status[Public status JSON]
  end

  subgraph storage [Storage]
    DB[(SQLite volume)]
  end

  UI -->|Bearer admin key| Monitors
  UI --> Public
  Public --> Status
  Scheduler --> Monitors
  Monitors --> DB
  Monitors --> Incidents
  Monitors --> Alerts
  Incidents --> DB
  Alerts -->|optional SMTP| Email[Email provider]
  Status --> DB
```

The backend serves JSON only. HTML status pages and the admin UI live in the separate frontend repo.

## Features

- **URL monitors** — outbound HTTP/HEAD checks with SSRF protections and response-time history
- **Scheduler** — single-process interval checks (ideal for Docker/self-host; not horizontally scaled yet)
- **Automatic incidents** — one incident per outage, timeline updates, acknowledge/resolve via admin API
- **Email alerts** — optional down/recovery emails via SMTP env vars (no secrets stored in DB)
- **Public status page JSON** — `/api/public/v1/status/{slug}` for a companion frontend to render
- **Admin auth** — `Authorization: Bearer $ADMIN_API_KEY` for mutating routes
- **Portfolio-compatible SLO endpoints** — synthetic `/api/v1/summary` and `/metrics` remain for demo dashboards when no real fleet data exists

## Local development (without Docker)

Requirements: Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
alembic upgrade head
DEMO_MODE=true uvicorn service_monitor.app:app --host 127.0.0.1 --port 8090 --reload
```

`DEMO_MODE=true` opens protected routes locally without an admin key. Use `DEMO_MODE=false` and `ADMIN_API_KEY=...` to match production behavior.

API docs: [http://127.0.0.1:8090/docs](http://127.0.0.1:8090/docs)

## Configuration

Copy `.env.example` to `.env` for Docker Compose, or export variables for bare-metal runs.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./service_monitor.db` | SQLAlchemy database URL |
| `ADMIN_API_KEY` | unset | Bearer token for admin routes when `DEMO_MODE=false` |
| `DEMO_MODE` | `false` | When `true`, allows protected routes without a key (local dev only) |
| `WEB_CORS_ORIGINS` | local Vite origins | Comma-separated exact browser origins |
| `SCHEDULER_ENABLED` | `false` (bare metal), `true` (Compose) | Automatic interval checks |
| `ALERTS_ENABLED` | `false` | Master switch for email alerts |
| `SMTP_*`, `ALERT_EMAIL_TO` | unset | SMTP credentials (**env only**, never commit) |
| `FRONTEND_PUBLIC_URL` | unset | Link appended to alert emails / status references |
| `CHECK_TIMEOUT_SECONDS` | `5` | Default outbound check timeout |
| `MAX_MONITORS` | `25` | Maximum persisted monitors |
| `DATA_RETENTION_DAYS` | `7` | Prune old check results |

## Security notes

- Set a strong `ADMIN_API_KEY` in production. Never commit it or put it in a frontend build.
- Keep `DEMO_MODE=false` on public deployments.
- SMTP passwords belong in server env only; the API never returns them.
- Outbound checks block private/loopback targets (SSRF guard).
- CORS allows explicit origins only — no wildcard `*`.

## Smoke tests

**Deployed / remote backend:**

```bash
BACKEND_URL=https://service-health-incident-monitor.onrender.com \
FRONTEND_ORIGIN=https://operations-dashboard-b8v.pages.dev \
python3 scripts/smoke_backend.py
```

Pass `ADMIN_API_KEY` to also verify protected routes.

**Self-hosted / local:**

```bash
BACKEND_URL=http://127.0.0.1:8090 \
ADMIN_API_KEY=your-local-secret \
python3 scripts/smoke_self_host.py
```

After `docker compose up`, allow startup time or set `SMOKE_WAIT_SECONDS=15`.

## Companion frontend

Deploy the [operations-dashboard](https://github.com/mithulram/operations-dashboard) separately:

```bash
VITE_API_BASE_URL=https://your-monitor-host.example.com npm run build
npx wrangler pages deploy dist --project-name=operations-dashboard --branch=main
```

Set `WEB_CORS_ORIGINS` on this backend to your frontend origin. Users paste `ADMIN_API_KEY` into the dashboard **Settings** page (stored in browser localStorage only).

## Deploy for free (Render)

The public demo runs on [Render](https://render.com) with `DEMO_MODE=false`, ephemeral SQLite, and `SCHEDULER_ENABLED=false` (free tier sleeps).

| Variable | Recommended Render value |
|---|---|
| `DEMO_MODE` | `false` |
| `ADMIN_API_KEY` | Strong secret in Render dashboard only |
| `WEB_CORS_ORIGINS` | `https://operations-dashboard-b8v.pages.dev` |
| `SCHEDULER_ENABLED` | `false` on free tier; use Docker self-host for scheduled checks |
| `ALERTS_ENABLED` | `false` until SMTP is configured |

See [`render.yaml`](render.yaml) for a starter Blueprint.

## API overview

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /healthz`, `GET /readyz` | Public | Liveness / readiness |
| `GET /api/v1/summary`, `GET /metrics` | Public | Fleet + synthetic SLO signals |
| `GET /api/v1/incidents` | Public | Incident list (real or demo fallback) |
| `GET /api/public/v1/status/{slug}` | Public | Public status page JSON |
| `GET/POST/PATCH/DELETE /api/v1/monitors...` | Admin | Monitor CRUD and checks |
| `GET/PATCH /api/v1/incidents/{id}...` | Mixed | Incident detail/timeline; mutations admin |
| `GET/PATCH /api/v1/settings/alerts...` | Admin | Email alert settings |
| `GET/PATCH /api/v1/status-page...` | Admin | Status page builder |

Full interactive docs: `/docs`

## Honest limitations

This is a **lightweight MVP**, not an enterprise incident platform:

- Single-instance scheduler (no horizontal worker pool yet)
- SQLite by default (Postgres-compatible schema, but not tuned for large fleets)
- Email alerts only — no Slack, PagerDuty, webhooks, or escalation policies
- No teams, RBAC, or multi-tenant accounts
- Synthetic SLO/error-budget endpoints remain for portfolio compatibility
- Render free tier is fine for demos; use Docker self-host for reliable scheduled monitoring

## Verify locally

```bash
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

## License

MIT. See [LICENSE](LICENSE).
