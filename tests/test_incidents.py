import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

import support  # noqa: F401
from support import test_database_url
from service_monitor.app import create_app
from service_monitor.config import Settings
from service_monitor.db.engine import session_scope
from service_monitor.db import repositories as repo
from service_monitor.services.state import get_or_create_monitor_state
from service_monitor.services.alerts import set_smtp_sender_for_tests
from service_monitor.services.check_runner import execute_monitor_check, reset_check_semaphore_for_tests
from service_monitor.state import MonitorState


MEMORY_DB = test_database_url()
PUBLIC_MONITOR = {
    "name": "Example API",
    "url": "https://example.com/health",
    "method": "GET",
}
ADMIN_HEADERS = {"Authorization": "Bearer expected-secret"}


def make_settings(**overrides: object) -> Settings:
    defaults = {
        "demo_mode": True,
        "admin_api_key": None,
        "database_url": MEMORY_DB,
        "scheduler_enabled": False,
        "alerts_enabled": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def make_client(**settings_overrides: object) -> TestClient:
    settings = make_settings(**settings_overrides)
    return TestClient(create_app(MonitorState(), settings=settings))


class AutoIncidentTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_check_semaphore_for_tests()
        set_smtp_sender_for_tests(lambda **kwargs: None)
        self.getaddrinfo_patcher = mock.patch(
            "service_monitor.ssrf.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
        )
        self.getaddrinfo_patcher.start()

    def tearDown(self) -> None:
        self.getaddrinfo_patcher.stop()
        set_smtp_sender_for_tests(None)
        reset_check_semaphore_for_tests()

    def _create_monitor(self, client: TestClient) -> int:
        return client.post("/api/v1/monitors", json=PUBLIC_MONITOR).json()["id"]

    def _run_check(self, monitor_id: int, status_code: int, **settings_overrides: object) -> None:
        settings = make_settings(**settings_overrides)
        mock_http = mock.Mock()
        mock_http.__enter__ = mock.Mock(return_value=mock_http)
        mock_http.__exit__ = mock.Mock(return_value=False)
        mock_http.request.return_value = httpx.Response(status_code)
        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            with session_scope() as session:
                execute_monitor_check(session, monitor_id, settings)

    def test_failed_check_creates_one_incident(self):
        client = make_client()
        monitor_id = self._create_monitor(client)
        self._run_check(monitor_id, 503)

        incidents = client.get("/api/v1/incidents").json()
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["status"], "OPEN")
        self.assertEqual(incidents[0]["monitor_id"], monitor_id)
        self.assertIn("Example API is down", incidents[0]["title"])

        with session_scope() as session:
            state = get_or_create_monitor_state(session, monitor_id)
            self.assertIsNotNone(state.open_incident_id)

    def test_repeated_failed_check_does_not_duplicate_incident(self):
        client = make_client()
        monitor_id = self._create_monitor(client)
        self._run_check(monitor_id, 503)
        self._run_check(monitor_id, 503)

        incidents = client.get("/api/v1/incidents").json()
        self.assertEqual(len(incidents), 1)

    def test_recovery_resolves_incident(self):
        client = make_client()
        monitor_id = self._create_monitor(client)
        self._run_check(monitor_id, 503)
        self._run_check(monitor_id, 200)

        incidents = client.get("/api/v1/incidents").json()
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["status"], "RESOLVED")
        self.assertIsNotNone(incidents[0]["resolved_at"])

        with session_scope() as session:
            state = get_or_create_monitor_state(session, monitor_id)
            self.assertIsNone(state.open_incident_id)

    def test_paused_monitor_does_not_create_incident(self):
        client = make_client()
        monitor_id = self._create_monitor(client)
        client.patch(f"/api/v1/monitors/{monitor_id}", json={"is_paused": True})
        self._run_check(monitor_id, 503)

        with session_scope() as session:
            self.assertEqual(repo.count_incidents(session), 0)

    def test_incidents_list_remains_public_and_backward_compatible(self):
        client = make_client()
        incidents = client.get("/api/v1/incidents").json()
        self.assertEqual(len(incidents), 2)
        self.assertIn("identifier", incidents[0])
        self.assertIn("service", incidents[0])
        self.assertIn("severity", incidents[0])
        self.assertIn("summary", incidents[0])

        monitor_id = self._create_monitor(client)
        self._run_check(monitor_id, 503)
        db_incidents = client.get("/api/v1/incidents").json()
        self.assertEqual(len(db_incidents), 1)
        payload = db_incidents[0]
        for field in ("identifier", "service", "severity", "status", "summary", "started_at"):
            self.assertIn(field, payload)
        self.assertIn("monitor_name", payload)

    def test_summary_open_incident_count_reflects_real_incidents(self):
        client = make_client()
        before = client.get("/api/v1/summary").json()["open_incident_count"]
        self.assertEqual(before, 1)

        monitor_id = self._create_monitor(client)
        self._run_check(monitor_id, 503)
        after = client.get("/api/v1/summary").json()["open_incident_count"]
        self.assertEqual(after, 1)

    def test_public_status_includes_recent_incidents(self):
        client = make_client()
        monitor_id = self._create_monitor(client)
        self._run_check(monitor_id, 503)

        payload = client.get("/api/public/v1/status/default").json()
        self.assertEqual(len(payload["recent_incidents"]), 1)
        incident = payload["recent_incidents"][0]
        self.assertIn("title", incident)
        self.assertIn("status", incident)
        self.assertIn("updates_count", incident)

    def test_alert_dedupe_still_works_with_incidents(self):
        sent: list[dict[str, object]] = []
        set_smtp_sender_for_tests(lambda **kwargs: sent.append(kwargs))
        client = make_client(
            alerts_enabled=True,
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="smtp-user",
            smtp_password="smtp-pass",
            smtp_from="monitor@example.com",
            alert_email_to="alerts@example.com",
        )
        client.patch("/api/v1/settings/alerts", json={"enabled": True})
        monitor_id = self._create_monitor(client)

        self._run_check(
            monitor_id,
            503,
            alerts_enabled=True,
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="smtp-user",
            smtp_password="smtp-pass",
            smtp_from="monitor@example.com",
            alert_email_to="alerts@example.com",
        )
        self._run_check(
            monitor_id,
            503,
            alerts_enabled=True,
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="smtp-user",
            smtp_password="smtp-pass",
            smtp_from="monitor@example.com",
            alert_email_to="alerts@example.com",
        )
        self.assertEqual(len(sent), 1)


class IncidentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_check_semaphore_for_tests()
        set_smtp_sender_for_tests(lambda **kwargs: None)
        self.getaddrinfo_patcher = mock.patch(
            "service_monitor.ssrf.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
        )
        self.getaddrinfo_patcher.start()

    def tearDown(self) -> None:
        self.getaddrinfo_patcher.stop()
        set_smtp_sender_for_tests(None)
        reset_check_semaphore_for_tests()

    def _create_open_incident(self, client: TestClient, headers: dict[str, str] | None = None) -> int:
        request_headers = headers or {}
        monitor_id = client.post("/api/v1/monitors", json=PUBLIC_MONITOR, headers=request_headers).json()["id"]
        settings = make_settings()
        mock_http = mock.Mock()
        mock_http.__enter__ = mock.Mock(return_value=mock_http)
        mock_http.__exit__ = mock.Mock(return_value=False)
        mock_http.request.return_value = httpx.Response(503)
        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            with session_scope() as session:
                execute_monitor_check(session, monitor_id, settings)
        return client.get("/api/v1/incidents").json()[0]["id"]

    def test_manual_acknowledge_and_resolve_require_auth(self):
        client = make_client(demo_mode=False, admin_api_key="expected-secret")
        incident_id = self._create_open_incident(client, headers=ADMIN_HEADERS)

        unauth = client.patch(f"/api/v1/incidents/{incident_id}", json={"status": "acknowledged"})
        self.assertEqual(unauth.status_code, 401)

        ack = client.patch(
            f"/api/v1/incidents/{incident_id}",
            json={"status": "acknowledged"},
            headers=ADMIN_HEADERS,
        )
        self.assertEqual(ack.status_code, 200)
        self.assertEqual(ack.json()["status"], "ACKNOWLEDGED")
        self.assertIsNotNone(ack.json()["acknowledged_at"])

        resolved = client.patch(
            f"/api/v1/incidents/{incident_id}",
            json={"status": "resolved"},
            headers=ADMIN_HEADERS,
        )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["status"], "RESOLVED")
        self.assertIsNotNone(resolved.json()["resolved_at"])

    def test_adding_incident_update_works(self):
        client = make_client(demo_mode=False, admin_api_key="expected-secret")
        incident_id = self._create_open_incident(client, headers=ADMIN_HEADERS)

        unauth = client.post(
            f"/api/v1/incidents/{incident_id}/updates",
            json={"message": "Investigating root cause."},
        )
        self.assertEqual(unauth.status_code, 401)

        response = client.post(
            f"/api/v1/incidents/{incident_id}/updates",
            json={"message": "Investigating root cause."},
            headers=ADMIN_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        updates = client.get(f"/api/v1/incidents/{incident_id}/updates").json()
        self.assertGreaterEqual(len(updates), 2)
        self.assertTrue(any(item["message"] == "Investigating root cause." for item in updates))


if __name__ == "__main__":
    unittest.main()
