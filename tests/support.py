"""Shared helpers for backend unit tests."""

from __future__ import annotations

import os

DEFAULT_TEST_DATABASE_URL = "sqlite:///:memory:"


def test_database_url() -> str:
    value = os.environ.get("DATABASE_URL", DEFAULT_TEST_DATABASE_URL).strip()
    return value or DEFAULT_TEST_DATABASE_URL


def uses_postgres() -> bool:
    return test_database_url().startswith("postgresql")
