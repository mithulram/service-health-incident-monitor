"""Shared helpers for backend unit tests."""

from __future__ import annotations

import os

DEFAULT_TEST_DATABASE_URL = "sqlite:///:memory:"


def test_database_url() -> str:
    pg_host = os.environ.get("PGHOST", "").strip()
    if pg_host:
        pg_port = os.environ.get("PGPORT", "5432").strip()
        pg_user = os.environ.get("PGUSER", "").strip()
        pg_password = os.environ.get("PGPASSWORD", "").strip()
        pg_database = os.environ.get("PGDATABASE", "").strip()
        if pg_user and pg_password and pg_database:
            return (
                f"postgresql+psycopg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_database}"
            )

    value = os.environ.get("DATABASE_URL", DEFAULT_TEST_DATABASE_URL).strip()
    return value or DEFAULT_TEST_DATABASE_URL


def uses_postgres() -> bool:
    return test_database_url().startswith("postgresql")
