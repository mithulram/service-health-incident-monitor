import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from service_monitor.app import create_app
from service_monitor.config import Settings
from service_monitor.ssrf import SSRFError, validate_monitor_url
from service_monitor.state import MonitorState


MEMORY_DB = "sqlite:///:memory:"
PUBLIC_MONITOR = {
    "name": "Example API",
    "url": "https://example.com/health",
    "method": "GET",
}


def make_client(
    *,
    demo_mode: bool = True,
    admin_api_key: str | None = None,
    database_url: str = MEMORY_DB,
) -> TestClient:
    settings = Settings(
        demo_mode=demo_mode,
        admin_api_key=admin_api_key,
        database_url=database_url,
    )
    return TestClient(create_app(MonitorState(), settings=settings))


class MonitorApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.getaddrinfo_patcher = mock.patch(
            "service_monitor.ssrf.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
        )
        self.getaddrinfo_patcher.start()

    def tearDown(self) -> None:
        self.getaddrinfo_patcher.stop()

    def test_create_list_get_update_delete_monitor(self):
        client = make_client()

        create_response = client.post("/api/v1/monitors", json=PUBLIC_MONITOR)
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()
        self.assertEqual(created["name"], PUBLIC_MONITOR["name"])
        monitor_id = created["id"]

        list_response = client.get("/api/v1/monitors")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        get_response = client.get(f"/api/v1/monitors/{monitor_id}")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["url"], PUBLIC_MONITOR["url"])

        patch_response = client.patch(
            f"/api/v1/monitors/{monitor_id}",
            json={"name": "Updated API", "is_paused": True},
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["name"], "Updated API")
        self.assertTrue(patch_response.json()["is_paused"])

        delete_response = client.delete(f"/api/v1/monitors/{monitor_id}")
        self.assertEqual(delete_response.status_code, 204)
        self.assertEqual(client.get("/api/v1/monitors").json(), [])

    def test_protected_routes_reject_invalid_admin_key(self):
        client = make_client(demo_mode=False, admin_api_key="expected-secret")

        response = client.post(
            "/api/v1/monitors",
            json=PUBLIC_MONITOR,
            headers={"Authorization": "Bearer wrong-secret"},
        )
        self.assertEqual(response.status_code, 403)

    def test_protected_routes_accept_valid_admin_key(self):
        client = make_client(demo_mode=False, admin_api_key="expected-secret")
        headers = {"Authorization": "Bearer expected-secret"}

        response = client.post("/api/v1/monitors", json=PUBLIC_MONITOR, headers=headers)
        self.assertEqual(response.status_code, 201)

        monitor_id = response.json()["id"]
        list_response = client.get("/api/v1/monitors", headers=headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        run_response = client.post(f"/api/v1/checks/run/{monitor_id}", headers=headers)
        self.assertEqual(run_response.status_code, 200)

    def test_protected_routes_reject_missing_admin_key_when_not_demo(self):
        client = make_client(demo_mode=False, admin_api_key=None)
        response = client.get("/api/v1/monitors")
        self.assertEqual(response.status_code, 503)

    def test_manual_check_records_success_with_mocked_http(self):
        client = make_client()
        monitor_id = client.post("/api/v1/monitors", json=PUBLIC_MONITOR).json()["id"]

        mock_http = mock.Mock()
        mock_http.request.return_value = httpx.Response(200)

        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            response = client.post(f"/api/v1/checks/run/{monitor_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["status_code"], 200)
        self.assertIsNotNone(payload["response_time_ms"])
        self.assertIsNone(payload["error_message"])

    def test_manual_check_records_failure_for_unexpected_status(self):
        client = make_client()
        monitor_id = client.post("/api/v1/monitors", json=PUBLIC_MONITOR).json()["id"]

        mock_http = mock.Mock()
        mock_http.request.return_value = httpx.Response(503)

        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            response = client.post(f"/api/v1/checks/run/{monitor_id}")

        payload = response.json()
        self.assertFalse(payload["success"])
        self.assertEqual(payload["status_code"], 503)
        self.assertIn("Unexpected status code", payload["error_message"])

    def test_manual_check_records_timeout_failure(self):
        client = make_client()
        monitor_id = client.post("/api/v1/monitors", json=PUBLIC_MONITOR).json()["id"]

        mock_http = mock.Mock()
        mock_http.request.side_effect = httpx.TimeoutException("timed out")

        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            response = client.post(f"/api/v1/checks/run/{monitor_id}")

        payload = response.json()
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_message"], "Request timed out.")

    def test_create_monitor_rejects_localhost_url(self):
        client = make_client()
        response = client.post(
            "/api/v1/monitors",
            json={
                "name": "Local",
                "url": "http://127.0.0.1/health",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("blocked", response.json()["detail"].lower())


class SSRFGuardTests(unittest.TestCase):
    def test_rejects_localhost_hostname(self):
        with self.assertRaises(SSRFError):
            validate_monitor_url("http://localhost/health")

    def test_rejects_private_ip_literal(self):
        with self.assertRaises(SSRFError):
            validate_monitor_url("http://10.0.0.5/health")

    def test_rejects_file_scheme(self):
        with self.assertRaises(SSRFError):
            validate_monitor_url("file:///etc/passwd")

    def test_rejects_loopback_ipv6(self):
        with self.assertRaises(SSRFError):
            validate_monitor_url("http://[::1]/health")

    @mock.patch("service_monitor.ssrf.socket.getaddrinfo")
    def test_rejects_hostname_resolving_to_private_ip(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("192.168.1.20", 80)),
        ]
        with self.assertRaises(SSRFError):
            validate_monitor_url("http://public.example/health")
