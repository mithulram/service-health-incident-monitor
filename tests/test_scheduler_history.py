import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import support  # noqa: F401
from support import test_database_url
from service_monitor.app import create_app
from service_monitor.config import Settings
from service_monitor.db.engine import create_all_tables, init_engine, session_scope
from service_monitor.db import repositories as repo
from service_monitor.db.models import CheckResult, MonitorState as MonitorStateRow
from service_monitor.scheduler import MonitorScheduler, _run_scheduled_check
from service_monitor.services.check_runner import execute_monitor_check, reset_check_semaphore_for_tests
from service_monitor.services.checks import CheckOutcome
from service_monitor.services.state import record_check_result
from service_monitor.state import MonitorState


MEMORY_DB = test_database_url()
PUBLIC_MONITOR = {
    "name": "Example API",
    "url": "https://example.com/health",
    "method": "GET",
}


def make_settings(**overrides: object) -> Settings:
    defaults = {
        "demo_mode": True,
        "admin_api_key": None,
        "database_url": MEMORY_DB,
        "scheduler_enabled": False,
        "data_retention_days": 7,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def make_client(**settings_overrides: object) -> TestClient:
    settings = make_settings(**settings_overrides)
    return TestClient(create_app(MonitorState(), settings=settings, database_url=settings.database_url))


class SchedulerHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_check_semaphore_for_tests()
        self.getaddrinfo_patcher = mock.patch(
            "service_monitor.ssrf.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
        )
        self.getaddrinfo_patcher.start()

    def tearDown(self) -> None:
        self.getaddrinfo_patcher.stop()
        reset_check_semaphore_for_tests()

    def test_manual_check_creates_check_result_and_monitor_state(self):
        client = make_client()
        monitor_id = client.post("/api/v1/monitors", json=PUBLIC_MONITOR).json()["id"]

        mock_http = mock.Mock()
        mock_http.request.return_value = httpx.Response(200)

        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            response = client.post(f"/api/v1/checks/run/{monitor_id}")

        self.assertEqual(response.status_code, 200)
        monitor = client.get(f"/api/v1/monitors/{monitor_id}").json()
        self.assertEqual(monitor["last_status"], "up")
        self.assertEqual(monitor["consecutive_failures"], 0)
        self.assertIsNotNone(monitor["last_check_at"])
        self.assertEqual(monitor["uptime_ratio_24h"], 1.0)

        checks = client.get(f"/api/v1/monitors/{monitor_id}/checks").json()
        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0]["success"])

    def test_failed_checks_increment_consecutive_failures(self):
        client = make_client()
        monitor_id = client.post("/api/v1/monitors", json=PUBLIC_MONITOR).json()["id"]
        mock_http = mock.Mock()
        mock_http.request.return_value = httpx.Response(503)

        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            client.post(f"/api/v1/checks/run/{monitor_id}")
            client.post(f"/api/v1/checks/run/{monitor_id}")

        monitor = client.get(f"/api/v1/monitors/{monitor_id}").json()
        self.assertEqual(monitor["last_status"], "down")
        self.assertEqual(monitor["consecutive_failures"], 2)

    def test_successful_check_resets_consecutive_failures(self):
        client = make_client()
        monitor_id = client.post("/api/v1/monitors", json=PUBLIC_MONITOR).json()["id"]
        mock_http = mock.Mock()
        mock_http.request.side_effect = [httpx.Response(503), httpx.Response(200)]

        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            client.post(f"/api/v1/checks/run/{monitor_id}")
            client.post(f"/api/v1/checks/run/{monitor_id}")

        monitor = client.get(f"/api/v1/monitors/{monitor_id}").json()
        self.assertEqual(monitor["last_status"], "up")
        self.assertEqual(monitor["consecutive_failures"], 0)

    def test_uptime_ratios_calculated_from_check_history(self):
        settings = make_settings()
        init_engine(MEMORY_DB)
        create_all_tables()

        with session_scope() as session:
            monitor = repo.create_monitor(
                session,
                name="Ratio test",
                url="https://example.com",
                method="GET",
                interval_seconds=60,
                timeout_seconds=5,
                expected_status_min=200,
                expected_status_max=399,
                is_paused=False,
            )
            now = datetime.now(UTC)
            outcomes = [
                CheckOutcome(now - timedelta(hours=1), 200, 100, True, None),
                CheckOutcome(now - timedelta(hours=2), 200, 120, True, None),
                CheckOutcome(now - timedelta(hours=3), 503, 90, False, "fail"),
            ]
            for outcome in outcomes:
                record_check_result(session, monitor, outcome, settings)

            state = session.get(MonitorStateRow, monitor.id)
            assert state is not None
            self.assertAlmostEqual(state.uptime_ratio_24h, 2 / 3, places=3)
            self.assertAlmostEqual(state.uptime_ratio_7d, 2 / 3, places=3)

    def test_check_history_returns_newest_first_and_respects_limit(self):
        client = make_client()
        monitor_id = client.post("/api/v1/monitors", json=PUBLIC_MONITOR).json()["id"]
        mock_http = mock.Mock()
        mock_http.request.return_value = httpx.Response(200)

        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            for _ in range(3):
                client.post(f"/api/v1/checks/run/{monitor_id}")

        checks = client.get(f"/api/v1/monitors/{monitor_id}/checks?limit=2").json()
        self.assertEqual(len(checks), 2)
        self.assertGreater(checks[0]["checked_at"], checks[1]["checked_at"])

    def test_summary_includes_fleet_fields_and_preserves_synthetic_fields(self):
        client = make_client()
        payload = client.get("/api/v1/summary").json()

        for key in (
            "requests_total",
            "requests_successful",
            "requests_failed",
            "availability_ratio",
            "slo_target_ratio",
            "error_budget_remaining_ratio",
            "open_incident_count",
            "monitors_total",
            "monitors_up",
            "monitors_down",
            "monitors_paused",
            "monitors_unknown",
            "average_response_time_ms_24h",
        ):
            self.assertIn(key, payload)

        self.assertEqual(payload["monitors_total"], 0)
        self.assertEqual(payload["requests_total"], 400)

    def test_scheduler_registers_active_monitor_only(self):
        settings = make_settings(scheduler_enabled=True)
        init_engine(MEMORY_DB)
        create_all_tables()

        with session_scope() as session:
            active = repo.create_monitor(
                session,
                name="Active",
                url="https://example.com/a",
                method="GET",
                interval_seconds=60,
                timeout_seconds=5,
                expected_status_min=200,
                expected_status_max=399,
                is_paused=False,
            )
            active_id = active.id
            paused = repo.create_monitor(
                session,
                name="Paused",
                url="https://example.com/b",
                method="GET",
                interval_seconds=60,
                timeout_seconds=5,
                expected_status_min=200,
                expected_status_max=399,
                is_paused=True,
            )
            paused_id = paused.id

        scheduler = MonitorScheduler(settings)
        scheduler.start()
        self.assertIsNotNone(scheduler._scheduler.get_job(f"monitor-check-{active_id}"))
        self.assertIsNone(scheduler._scheduler.get_job(f"monitor-check-{paused_id}"))
        scheduler.shutdown()

    def test_scheduler_runs_due_monitor_without_network(self):
        settings = make_settings(scheduler_enabled=True)
        init_engine(MEMORY_DB)
        create_all_tables()

        with session_scope() as session:
            monitor = repo.create_monitor(
                session,
                name="Scheduled",
                url="https://example.com",
                method="GET",
                interval_seconds=60,
                timeout_seconds=5,
                expected_status_min=200,
                expected_status_max=399,
                is_paused=False,
            )
            monitor_id = monitor.id

        mock_http = mock.Mock()
        mock_http.request.return_value = httpx.Response(200)
        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            _run_scheduled_check(monitor_id, settings)

        with session_scope() as session:
            count = session.scalar(
                select(func.count()).select_from(CheckResult).where(CheckResult.monitor_id == monitor_id)
            )
            state = session.get(MonitorStateRow, monitor_id)
            self.assertEqual(count, 1)
            assert state is not None
            self.assertEqual(state.last_status, "up")

    def test_paused_monitor_reports_paused_state(self):
        client = make_client()
        payload = {**PUBLIC_MONITOR, "is_paused": True}
        monitor = client.post("/api/v1/monitors", json=payload).json()
        self.assertEqual(monitor["last_status"], "paused")

    def test_pruning_removes_old_check_results(self):
        settings = make_settings(data_retention_days=7)
        init_engine(MEMORY_DB)
        create_all_tables()

        with session_scope() as session:
            monitor = repo.create_monitor(
                session,
                name="Retention",
                url="https://example.com",
                method="GET",
                interval_seconds=60,
                timeout_seconds=5,
                expected_status_min=200,
                expected_status_max=399,
                is_paused=False,
            )
            old_outcome = CheckOutcome(
                datetime.now(UTC) - timedelta(days=8),
                200,
                50,
                True,
                None,
            )
            record_check_result(session, monitor, old_outcome, settings)
            fresh_outcome = CheckOutcome(datetime.now(UTC), 200, 60, True, None)
            record_check_result(session, monitor, fresh_outcome, settings)

            remaining = session.scalar(
                select(func.count()).select_from(CheckResult).where(CheckResult.monitor_id == monitor.id)
            )
            self.assertEqual(remaining, 1)
