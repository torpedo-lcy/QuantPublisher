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
