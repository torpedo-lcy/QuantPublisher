"""KRX 종목 목록 수집기 테스트.

- fixture 기반 파싱 테스트: parse_krx_listing이 검증/중복 처리를 올바르게 하는지 확인.
- DB 저장 테스트: save_krx_listing / collect_krx_listing이 실제 SQLite에 저장하는지 확인.
- fetch_krx_listing은 네트워크를 호출하지 않도록 FinanceDataReader를 monkeypatch로 대체한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantpublisher.crawler.krx_listing import (
    KrxListingFetchError,
    collect_krx_listing,
    fetch_krx_listing,
    parse_krx_listing,
    save_krx_listing,
)
from quantpublisher.database.core import Database, init_db
from quantpublisher.database.security_repository import SecurityRepository

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    with (FIXTURES_DIR / name).open("r", encoding="utf-8") as f:
        return json.load(f)


# ── parse_krx_listing: fixture 기반 파싱 테스트 ──────────────────────────


def test_parse_krx_listing_filters_invalid_and_dedups_by_code():
    raw_rows = _load_fixture("krx_listing_sample.json")

    result = parse_krx_listing(raw_rows)
    result_by_code = {s.stock_code: s for s in result}

    # 유효한 종목코드: 005930(중복 2건 -> 1건), 035720, 058470 = 3건
    assert len(result) == 3
    assert set(result_by_code) == {"005930", "035720", "058470"}

    # 중복된 종목코드는 마지막 행의 값으로 덮어써야 한다.
    assert result_by_code["005930"].name == "삼성전자(수정)"
    assert result_by_code["035720"].market == "KOSDAQ"
    assert result_by_code["058470"].market == "KONEX"


def test_parse_krx_listing_skips_missing_code_name_and_invalid_market():
    raw_rows = [
        {"Code": "", "Name": "코드없음", "Market": "KOSPI"},
        {"Code": "123456", "Name": "", "Market": "KOSPI"},
        {"Code": "12345", "Name": "코드길이오류", "Market": "KOSPI"},
        {"Code": "999999", "Name": "시장오류", "Market": "NASDAQ"},
    ]

    result = parse_krx_listing(raw_rows)

    assert result == []


def test_parse_krx_listing_returns_empty_list_for_empty_input():
    assert parse_krx_listing([]) == []


# ── fetch_krx_listing: FinanceDataReader 호출은 monkeypatch로 대체 ──────────


class _FakeDataFrame:
    def __init__(self, records: list[dict]) -> None:
        self._records = records

    def to_dict(self, orient: str) -> list[dict]:
        assert orient == "records"
        return self._records


def test_fetch_krx_listing_converts_dataframe_to_list_of_dict(monkeypatch: pytest.MonkeyPatch):
    records = _load_fixture("krx_listing_sample.json")
    fake_fdr = SimpleNamespace(StockListing=lambda market: _FakeDataFrame(records))
    monkeypatch.setitem(sys.modules, "FinanceDataReader", fake_fdr)

    result = fetch_krx_listing()

    assert result == records


def test_fetch_krx_listing_raises_when_financedatareader_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "FinanceDataReader", None)

    with pytest.raises(KrxListingFetchError):
        fetch_krx_listing()


def test_fetch_krx_listing_wraps_library_errors(monkeypatch: pytest.MonkeyPatch):
    def _raise_market_error(market: str):
        raise RuntimeError("network unreachable")

    fake_fdr = SimpleNamespace(StockListing=_raise_market_error)
    monkeypatch.setitem(sys.modules, "FinanceDataReader", fake_fdr)

    with pytest.raises(KrxListingFetchError):
        fetch_krx_listing()


# ── save_krx_listing / collect_krx_listing: DB 저장 테스트 ─────────────────


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "quantpublisher_test.sqlite3"
    init_db(path)
    return path


def test_save_krx_listing_persists_securities(db_path: Path):
    securities = parse_krx_listing(_load_fixture("krx_listing_sample.json"))
    database = Database(db_path)

    with database.transaction() as connection:
        saved_count = save_krx_listing(connection, securities)

    assert saved_count == len(securities)

    with database.connect() as connection:
        repository = SecurityRepository(connection)
        stored = repository.get_by_code("005930")
        assert stored is not None
        assert stored.name == "삼성전자(수정)"
        assert stored.market == "KOSPI"
        assert len(repository.list_all()) == len(securities)


def test_save_krx_listing_upsert_is_idempotent(db_path: Path):
    securities = parse_krx_listing(_load_fixture("krx_listing_sample.json"))
    database = Database(db_path)

    with database.transaction() as connection:
        save_krx_listing(connection, securities)
    with database.transaction() as connection:
        save_krx_listing(connection, securities)

    with database.connect() as connection:
        repository = SecurityRepository(connection)
        assert len(repository.list_all()) == len(securities)


def test_collect_krx_listing_fetches_parses_and_saves(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
):
    records = _load_fixture("krx_listing_sample.json")
    fake_fdr = SimpleNamespace(StockListing=lambda market: _FakeDataFrame(records))
    monkeypatch.setitem(sys.modules, "FinanceDataReader", fake_fdr)

    database = Database(db_path)
    with database.transaction() as connection:
        count = collect_krx_listing(connection)

    expected = len(parse_krx_listing(records))
    assert count == expected

    with database.connect() as connection:
        repository = SecurityRepository(connection)
        assert len(repository.list_all()) == expected
