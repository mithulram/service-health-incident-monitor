#!/usr/bin/env python3
"""End-to-end smoke test for a self-hosted monitor API instance."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

from smoke_backend import ENDPOINTS, check, request_with_retry


def run_monitor_lifecycle(base_url: str, admin_api_key: str) -> None:
    auth_headers = {"Authorization": f"Bearer {admin_api_key}"}
    suffix = uuid.uuid4().hex[:8]
    monitor_payload = json.dumps(
        {
            "name": f"Smoke test {suffix}",
            "url": "https://example.com",
            "method": "GET",
        }
    ).encode("utf-8")

    _, create_body = request_with_retry(
        "Create monitor",
        f"{base_url}/api/v1/monitors",
        method="POST",
        headers=auth_headers,
        body=monitor_payload,
        expected_status={200, 201},
    )
    monitor = json.loads(create_body.decode("utf-8"))
    monitor_id = monitor["id"]
    print(f"OK   Created monitor id={monitor_id}")

    request_with_retry(
        "Run monitor check",
        f"{base_url}/api/v1/checks/run/{monitor_id}",
        method="POST",
        headers=auth_headers,
        expected_status=200,
    )
    print(f"OK   Ran check for monitor id={monitor_id}")

    _, history_body = request_with_retry(
        "Fetch check history",
        f"{base_url}/api/v1/monitors/{monitor_id}/checks?limit=5",
        headers=auth_headers,
        expected_status=200,
    )
    history = json.loads(history_body.decode("utf-8"))
    if not isinstance(history, list) or not history:
        raise RuntimeError("Check history should contain at least one row after running a check.")
    print(f"OK   Check history returned {len(history)} row(s)")

    request_with_retry(
        "Delete monitor",
        f"{base_url}/api/v1/monitors/{monitor_id}",
        method="DELETE",
        headers=auth_headers,
        expected_status=204,
    )
    print(f"OK   Deleted monitor id={monitor_id}")


def main() -> int:
    backend_url = os.environ.get("BACKEND_URL", "http://127.0.0.1:8090").strip().rstrip("/")
    admin_api_key = os.environ.get("ADMIN_API_KEY", "").strip()
    wait_seconds = int(os.environ.get("SMOKE_WAIT_SECONDS", "0"))

    if wait_seconds > 0:
        print(f"Waiting {wait_seconds}s for service startup...")
        time.sleep(wait_seconds)

    print(f"Self-host smoke test against {backend_url}")
    try:
        for path in ENDPOINTS:
            check(backend_url, path)

        if not admin_api_key:
            print(
                "SKIP Monitor lifecycle: set ADMIN_API_KEY to exercise create/check/delete flows.",
                file=sys.stderr,
            )
        else:
            print("Running protected monitor lifecycle with ADMIN_API_KEY")
            run_monitor_lifecycle(backend_url, admin_api_key)
    except RuntimeError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        print("Self-host smoke test failed.", file=sys.stderr)
        return 1

    print("Self-host smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
