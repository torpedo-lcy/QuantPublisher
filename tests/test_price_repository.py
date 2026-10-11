from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from quantpublisher.database.connection import get_connection, initialize_schema
from quantpublisher.database.models import PriceDaily, Security
from quantpublisher.database.price_repository import PriceRepository
from quantpublisher.database.security_repository import SecurityRepository


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    conn = get_connection(tmp_path / "test.sqlite3")
    initialize_schema(conn)
    SecurityRepository(conn).upsert(Security("005930", "Samsung Electronics", "KOSPI"))
    SecurityRepository(conn).upsert(Security("000660", "SK Hynix", "KOSPI"))
    yield conn
    conn.close()


def _prices(code: str, days: int) -> list[PriceDaily]:
    return [
        PriceDaily(code, f"2026-01-{day:02d}", 1.0, 2.0, 0.5, float(day), 10.0)
        for day in range(1, days + 1)
    ]


def test_list_recent_by_code_returns_latest_rows_in_ascending_order(
    connection: sqlite3.Connection,
) -> None:
    repository = PriceRepository(connection)
    repository.upsert_many(_prices("005930", 10) + _prices("000660", 3))

    recent = repository.list_recent_by_code("005930", 4)

    assert [p.trade_date for p in recent] == [
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
        "2026-01-10",
    ]
    assert {p.stock_code for p in recent} == {"005930"}


def test_list_recent_by_code_returns_all_rows_when_fewer_than_limit(
    connection: sqlite3.Connection,
) -> None:
    repository = PriceRepository(connection)
    repository.upsert_many(_prices("005930", 3))

    assert len(repository.list_recent_by_code("005930", 370)) == 3
    assert repository.list_recent_by_code("000660", 370) == []
