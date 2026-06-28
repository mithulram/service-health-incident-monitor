import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import smoke_self_host  # noqa: E402


class SmokeSelfHostTests(unittest.TestCase):
    def test_run_monitor_lifecycle_creates_runs_and_deletes(self):
        responses = {
            ("POST", "/api/v1/monitors"): (200, json.dumps({"id": 42}).encode("utf-8")),
            ("POST", "/api/v1/checks/run/42"): (200, b"{}"),
            ("GET", "/api/v1/monitors/42/checks"): (200, json.dumps([{"success": True}]).encode()),
            ("DELETE", "/api/v1/monitors/42"): (204, b""),
        }

        def fake_request(label, url, *, method="GET", headers=None, body=None, expected_status=None):
            del label, headers, body, expected_status
            path = url.split("127.0.0.1:8090", 1)[-1]
            key = (method, path.split("?", 1)[0])
            if key not in responses:
                raise AssertionError(f"Unexpected request: {method} {path}")
            return responses[key]

        with mock.patch("smoke_self_host.request_with_retry", side_effect=fake_request):
            smoke_self_host.run_monitor_lifecycle("http://127.0.0.1:8090", "test-secret")

    def test_main_skips_lifecycle_without_admin_key(self):
        with mock.patch("smoke_self_host.check", return_value=True):
            with mock.patch("smoke_self_host.run_monitor_lifecycle") as lifecycle:
                with mock.patch.dict(os.environ, {"BACKEND_URL": "http://127.0.0.1:8090"}, clear=False):
                    os.environ.pop("ADMIN_API_KEY", None)
                    result = smoke_self_host.main()
        self.assertEqual(result, 0)
        lifecycle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
