from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from quantpublisher.database.connection import connect, get_connection, initialize_schema


def test_get_connection_creates_db_file(tmp_path: Path) -> None:
    db_path = tmp_path / "sub" / "test.sqlite3"

    connection = get_connection(db_path)
    connection.close()

    assert db_path.exists()


def test_initialize_schema_creates_securities_table(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    connection = get_connection(db_path)

    initialize_schema(connection)

    cursor = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='securities'"
    )
    assert cursor.fetchone() is not None
    connection.close()


def test_connect_context_manager_closes_connection(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"

    with connect(db_path) as connection:
        connection.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_connect_supports_transaction_commit(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"

    with connect(db_path) as connection:
        initialize_schema(connection)
        with connection:
            connection.execute(
                "INSERT INTO securities (stock_code, name, market) VALUES (?, ?, ?)",
                ("005930", "Samsung Electronics", "KOSPI"),
            )

    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT name FROM securities WHERE stock_code = ?", ("005930",)
        ).fetchone()
        assert row["name"] == "Samsung Electronics"


def test_initialize_schema_creates_prices_daily_table_and_corp_code_column(tmp_path: Path) -> None:
    connection = get_connection(tmp_path / "test.sqlite3")

    initialize_schema(connection)

    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    security_columns = {r[1] for r in connection.execute("PRAGMA table_info(securities)")}
    price_columns = {r[1] for r in connection.execute("PRAGMA table_info(prices_daily)")}
    assert "prices_daily" in tables
    assert "corp_code" in security_columns
    assert price_columns >= {"stock_code", "trade_date", "open", "high", "low", "close", "volume", "updated_at"}
    connection.close()


def test_initialize_schema_adds_corp_code_to_legacy_securities_table_keeping_rows(
    tmp_path: Path,
) -> None:
    # Task 003 시점의 securities (corp_code 없음)를 가진 기존 DB.
    db_path = tmp_path / "legacy.sqlite3"
    legacy = sqlite3.connect(db_path)
    with legacy:
        legacy.execute(
            "CREATE TABLE securities (stock_code TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "market TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        legacy.execute("INSERT INTO securities (stock_code, name, market) VALUES ('005930', '삼성전자', 'KOSPI')")
    legacy.close()

    connection = get_connection(db_path)
    initialize_schema(connection)
    initialize_schema(connection)  # 다시 호출해도 오류가 없어야 한다 (idempotent)

    row = connection.execute("SELECT name, corp_code FROM securities WHERE stock_code='005930'").fetchone()
    assert row["name"] == "삼성전자"
    assert row["corp_code"] is None
    connection.close()
