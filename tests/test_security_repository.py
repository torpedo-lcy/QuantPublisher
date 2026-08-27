from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from quantpublisher.database.connection import get_connection, initialize_schema
from quantpublisher.database.models import Security
from quantpublisher.database.security_repository import SecurityRepository


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    conn = get_connection(tmp_path / "test.sqlite3")
    initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def repository(connection: sqlite3.Connection) -> SecurityRepository:
    return SecurityRepository(connection)


def test_security_repository_upserts_new_security(repository: SecurityRepository) -> None:
    security = Security(stock_code="005930", name="Samsung Electronics", market="KOSPI")

    repository.upsert(security)
    found = repository.get_by_code("005930")

    assert found is not None
    assert found.name == "Samsung Electronics"
    assert found.market == "KOSPI"
    assert found.is_active is True


def test_security_repository_get_by_code_returns_none_when_missing(
    repository: SecurityRepository,
) -> None:
    assert repository.get_by_code("999999") is None


def test_security_repository_upserts_existing_code(repository: SecurityRepository) -> None:
    repository.upsert(Security(stock_code="005930", name="Samsung Electronics", market="KOSPI"))
    repository.upsert(Security(stock_code="005930", name="Samsung Elec.", market="KOSPI"))

    all_securities = repository.list_all()

    assert len(all_securities) == 1
    assert all_securities[0].name == "Samsung Elec."


def test_security_repository_list_all_returns_all_securities(
    repository: SecurityRepository,
) -> None:
    repository.upsert(Security(stock_code="005930", name="Samsung Electronics", market="KOSPI"))
    repository.upsert(Security(stock_code="000660", name="SK Hynix", market="KOSPI"))

    result = repository.list_all()

    assert {s.stock_code for s in result} == {"005930", "000660"}


def test_security_repository_list_all_active_only_filters_inactive(
    repository: SecurityRepository,
) -> None:
    repository.upsert(Security(stock_code="005930", name="Samsung Electronics", market="KOSPI"))
    repository.upsert(
        Security(stock_code="000660", name="SK Hynix", market="KOSPI", is_active=False)
    )

    result = repository.list_all(active_only=True)

    assert [s.stock_code for s in result] == ["005930"]


def test_security_repository_delete_removes_existing_security(
    repository: SecurityRepository,
) -> None:
    repository.upsert(Security(stock_code="005930", name="Samsung Electronics", market="KOSPI"))

    deleted = repository.delete("005930")

    assert deleted is True
    assert repository.get_by_code("005930") is None


def test_security_repository_delete_returns_false_when_not_found(
    repository: SecurityRepository,
) -> None:
    assert repository.delete("999999") is False
