#!/usr/bin/env python3
"""Verify Alembic migrations and basic Postgres connectivity for CI."""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text


def build_database_url() -> str:
    host = os.environ.get("PGHOST", "").strip()
    if not host:
        raise RuntimeError("PGHOST is required for Postgres verification")
    port = os.environ.get("PGPORT", "5432").strip()
    user = os.environ.get("PGUSER", "").strip()
    password = os.environ.get("PGPASSWORD", "").strip()
    database = os.environ.get("PGDATABASE", "").strip()
    if not (user and password and database):
        raise RuntimeError("PGUSER, PGPASSWORD, and PGDATABASE are required")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"


def main() -> int:
    url = build_database_url()
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if connection.execute(text("SELECT 1")).scalar_one() != 1:
                raise RuntimeError("Postgres connectivity check failed")
            tables = connection.execute(
                text("SELECT to_regclass('public.monitors') IS NOT NULL")
            ).scalar_one()
            if not tables:
                raise RuntimeError("Expected monitors table after Alembic migrations")
    finally:
        engine.dispose()

    print("Postgres migration verification passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Postgres migration verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
