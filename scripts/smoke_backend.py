#!/usr/bin/env python3
"""Smoke test a deployed Service Health & Incident Monitor backend."""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

ENDPOINTS = (
    "/healthz",
    "/api/v1/summary",
    "/api/v1/incidents",
    "/metrics",
)


def check(base_url: str, path: str) -> bool:
    url = f"{base_url}{path}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        print(f"FAIL {path}: HTTP {exc.code}", file=sys.stderr)
        return False
    except urllib.error.URLError as exc:
        print(f"FAIL {path}: {exc.reason}", file=sys.stderr)
        return False

    if status >= 400:
        print(f"FAIL {path}: HTTP {status}", file=sys.stderr)
        return False

    print(f"OK   {path}: HTTP {status} ({len(body)} bytes)")
    return True


def main() -> int:
    backend_url = os.environ.get("BACKEND_URL", "").strip().rstrip("/")
    if not backend_url:
        print("BACKEND_URL is required", file=sys.stderr)
        return 1

    print(f"Checking backend at {backend_url}")
    results = [check(backend_url, path) for path in ENDPOINTS]
    if all(results):
        print("Backend smoke test passed.")
        return 0

    print("Backend smoke test failed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
