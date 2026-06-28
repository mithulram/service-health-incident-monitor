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
        "alerts_enabled": True,
        "alert_email_to": "alerts@example.com",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "smtp-user",
        "smtp_password": "smtp-pass",
        "smtp_from": "monitor@example.com",
        "frontend_public_url": "https://operations-dashboard-b8v.pages.dev",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def make_client(**settings_overrides: object) -> TestClient:
    settings = make_settings(**settings_overrides)
    return TestClient(create_app(MonitorState(), settings=settings, database_url=settings.database_url))


class AlertServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_check_semaphore_for_tests()
        self.sent_messages: list[dict[str, object]] = []
        set_smtp_sender_for_tests(self._capture_smtp)
        self.getaddrinfo_patcher = mock.patch(
            "service_monitor.ssrf.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
        )
        self.getaddrinfo_patcher.start()

    def tearDown(self) -> None:
        self.getaddrinfo_patcher.stop()
        set_smtp_sender_for_tests(None)
        reset_check_semaphore_for_tests()

    def _capture_smtp(self, **kwargs: object) -> None:
        self.sent_messages.append(kwargs)

    def _create_monitor(self, client: TestClient) -> int:
        return client.post("/api/v1/monitors", json=PUBLIC_MONITOR).json()["id"]

    def _enable_alerts(self, client: TestClient) -> None:
        response = client.patch("/api/v1/settings/alerts", json={"enabled": True})
        self.assertEqual(response.status_code, 200)

    def _run_check(self, monitor_id: int, status_code: int, **settings_overrides: object) -> None:
        settings = make_settings(**settings_overrides)
        mock_http = mock.Mock()
        mock_http.__enter__ = mock.Mock(return_value=mock_http)
        mock_http.__exit__ = mock.Mock(return_value=False)
        mock_http.request.return_value = httpx.Response(status_code)
        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            with session_scope() as session:
                execute_monitor_check(session, monitor_id, settings)

    def test_alerts_disabled_does_not_send_email(self):
        client = make_client(alerts_enabled=False)
        monitor_id = self._create_monitor(client)
        self._enable_alerts(client)
        self._run_check(monitor_id, 503, alerts_enabled=False)
        self.assertEqual(self.sent_messages, [])

    def test_failed_check_opens_alert_once(self):
        client = make_client()
        monitor_id = self._create_monitor(client)
        self._enable_alerts(client)

        self._run_check(monitor_id, 503)
        self.assertEqual(len(self.sent_messages), 1)
        self.assertIn("[DOWN]", str(self.sent_messages[0]["subject"]))

        self._run_check(monitor_id, 503)
        self.assertEqual(len(self.sent_messages), 1)

    def test_recovery_sends_resolved_alert_when_enabled(self):
        client = make_client()
        monitor_id = self._create_monitor(client)
        self._enable_alerts(client)

        self._run_check(monitor_id, 503)
        self._run_check(monitor_id, 200)

        self.assertEqual(len(self.sent_messages), 2)
        self.assertIn("[RECOVERED]", str(self.sent_messages[1]["subject"]))

    def test_recovery_does_not_send_resolved_alert_when_disabled(self):
        client = make_client()
        monitor_id = self._create_monitor(client)
        client.patch("/api/v1/settings/alerts", json={"enabled": True, "send_resolved": False})

        self._run_check(monitor_id, 503)
        self._run_check(monitor_id, 200)

        self.assertEqual(len(self.sent_messages), 1)

    def test_check_execution_does_not_crash_if_smtp_fails(self):
        def fail_smtp(**kwargs: object) -> None:
            raise RuntimeError("smtp unavailable")

        set_smtp_sender_for_tests(fail_smtp)
        client = make_client()
        monitor_id = self._create_monitor(client)
        self._enable_alerts(client)

        self._run_check(monitor_id, 503)

        with session_scope() as session:
            events = repo.list_alert_events(session)
            self.assertEqual(len(events), 1)
            self.assertFalse(events[0].success)
            self.assertIn("smtp unavailable", events[0].error_message or "")

    def test_alert_events_records_success_and_failure(self):
        client = make_client()
        self._enable_alerts(client)
        response = client.post("/api/v1/settings/alerts/test")
        self.assertEqual(response.status_code, 200)

        with session_scope() as session:
            events = repo.list_alert_events(session)
            self.assertGreaterEqual(len(events), 1)
            self.assertTrue(events[0].success)


class AlertSettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        set_smtp_sender_for_tests(lambda **kwargs: None)

    def tearDown(self) -> None:
        set_smtp_sender_for_tests(None)

    def test_alert_settings_endpoint_requires_auth(self):
        client = make_client(demo_mode=False, admin_api_key="expected-secret")
        response = client.get("/api/v1/settings/alerts")
        self.assertEqual(response.status_code, 401)

    def test_alert_settings_endpoint_does_not_expose_smtp_password(self):
        client = make_client()
        response = client.get("/api/v1/settings/alerts")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("smtp_password", payload)
        self.assertTrue(payload["smtp_password_configured"])

    def test_test_email_endpoint_requires_auth(self):
        client = make_client(demo_mode=False, admin_api_key="expected-secret")
        response = client.post("/api/v1/settings/alerts/test")
        self.assertEqual(response.status_code, 401)

    def test_test_email_returns_config_error_when_smtp_missing(self):
        client = make_client(
            smtp_host=None,
            smtp_password=None,
            smtp_from=None,
            alert_email_to=None,
        )
        client.patch("/api/v1/settings/alerts", json={"enabled": True})
        response = client.post("/api/v1/settings/alerts/test")
        self.assertEqual(response.status_code, 400)
        self.assertIn("SMTP", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
