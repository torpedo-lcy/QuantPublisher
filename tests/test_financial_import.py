"""Task 014: quant.db 재무/밸류에이션 가져오기 테스트 (fixture 기반, 외부 접속 없음)."""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Iterator, Mapping

import pytest

from quantpublisher.crawler.external_mac import PriceExport
from quantpublisher.crawler.financial_import import (
    FinancialDataReadError,
    MetricParseStats,
    StatementParseStats,
    import_financial_data,
    parse_metric_rows,
    parse_statement_rows,
)
from quantpublisher.crawler.market_data_import import collect_market_data
from quantpublisher.database.connection import get_connection, initialize_schema
from quantpublisher.database.financial_repository import FinancialRepository
from quantpublisher.database.models import Security
from quantpublisher.database.security_repository import SecurityRepository

CURRENT_YEAR = 2026

# 원천 quant.db와 같은 열 구성 (eps, 현금흐름, YoY 포함 - 가져오지 않는지 확인하려고)
_SOURCE_SCHEMA = """
CREATE TABLE financial_data (
    stock_code TEXT NOT NULL, year INTEGER NOT NULL, report_type TEXT NOT NULL,
    assets REAL, liabilities REAL, equity REAL, current_assets REAL, current_liab REAL,
    sales REAL, gross_profit REAL, operating_income REAL, net_income REAL, eps REAL,
    cf_operating REAL, cf_investing REAL, cf_financing REAL,
    sales_yoy REAL, op_income_yoy REAL, net_income_yoy REAL,
    is_consolidated INTEGER DEFAULT 1, created_at TEXT,
    PRIMARY KEY (stock_code, year, report_type)
);
CREATE TABLE market_data (
    stock_code TEXT NOT NULL, year_month TEXT NOT NULL, trade_date TEXT,
    close_price REAL, market_cap REAL, shares_out REAL,
    per REAL, pbr REAL, psr REAL, pcr REAL,
    PRIMARY KEY (stock_code, year_month)
);
"""


def _statement(code: str, year: int = 2025, report_type: str = "11011", **overrides: object) -> dict:
    row = {
        "stock_code": code, "year": year, "report_type": report_type,
        "assets": 1000.0, "liabilities": 400.0, "equity": 600.0,
        "current_assets": 500.0, "current_liab": 300.0,
        "sales": 800.0, "gross_profit": 200.0, "operating_income": 100.0,
        "net_income": 60.0, "eps": 0.0,
        "cf_operating": 11.0, "cf_investing": -5.0, "cf_financing": -2.0,
        "sales_yoy": 3.0, "op_income_yoy": 4.0, "net_income_yoy": 5.0,
        "is_consolidated": 1, "created_at": "2026-03-26 00:00:00",
    }
    row.update(overrides)
    return row


def _metric(code: str, year_month: str = "2026-07", **overrides: object) -> dict:
    row = {
        "stock_code": code, "year_month": year_month, "trade_date": f"{year_month}-28",
        "close_price": 70000.0, "market_cap": 4.2e14, "shares_out": 6.0e9,
        "per": 12.5, "pbr": 1.4, "psr": 1.1, "pcr": 5.0,
    }
    row.update(overrides)
    return row


def _make_quant_db(path: Path, statements: list[dict], metrics: list[dict]) -> Path:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SOURCE_SCHEMA)
        for row in statements:
            columns = ", ".join(row)
            marks = ", ".join(f":{name}" for name in row)
            connection.execute(f"INSERT INTO financial_data ({columns}) VALUES ({marks})", row)
        for row in metrics:
            columns = ", ".join(row)
            marks = ", ".join(f":{name}" for name in row)
            connection.execute(f"INSERT INTO market_data ({columns}) VALUES ({marks})", row)
        connection.commit()
    finally:
        connection.close()
    return path


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = get_connection(tmp_path / "test.sqlite3")
    initialize_schema(conn)
    repository = SecurityRepository(conn)
    repository.upsert(Security(stock_code="005930", name="Samsung Electronics", market="KOSPI"))
    repository.upsert(Security(stock_code="000660", name="SK hynix", market="KOSPI"))
    yield conn
    conn.close()


@pytest.fixture
def repository(connection: sqlite3.Connection) -> FinancialRepository:
    return FinancialRepository(connection)


def _import(connection: sqlite3.Connection, quant_db: Path):
    return import_financial_data(connection, quant_db, current_year=CURRENT_YEAR)


# ── 스키마 ──────────────────────────────────────────────────────────────


def test_initialize_schema_creates_financial_tables_and_is_idempotent(
    connection: sqlite3.Connection,
) -> None:
    initialize_schema(connection)  # 재호출해도 오류가 없어야 한다

    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"financial_statements", "financial_metrics"} <= tables
    columns = {row[1] for row in connection.execute("PRAGMA table_info(financial_statements)")}
    assert "eps" not in columns
    assert not {"cf_operating", "sales_yoy"} & columns


# ── 재무제표 ────────────────────────────────────────────────────────────


def test_import_upserts_annual_statements_into_financial_statements(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [_statement("005930", 2024, sales=700.0), _statement("005930", 2025)],
        [],
    )

    result = _import(connection, quant_db)

    saved = repository.list_statements("005930")
    assert [s.year for s in saved] == [2024, 2025]
    assert saved[1].assets == 1000.0
    assert saved[1].equity == 600.0
    assert saved[1].sales == 800.0
    assert saved[1].is_consolidated == 1
    assert saved[0].report_type == "11011"
    assert result.statements_saved == 2


def test_import_excludes_non_annual_report_types(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [
            _statement("005930", 2025, "11011"),
            _statement("005930", 2025, "11012"),
            _statement("005930", 2025, "11013"),
            _statement("005930", 2025, "11014"),
        ],
        [],
    )

    _import(connection, quant_db)

    assert [s.report_type for s in repository.list_statements("005930")] == ["11011"]


def test_import_stores_net_income_zero_as_null_not_zero(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    # 잠정실적 공시: 매출/영업이익은 있고 순이익만 0.0 (= 미공시)
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [
            _statement("005930", 2025, net_income=0.0),
            _statement("000660", 2025, net_income=60.0),
        ],
        [],
    )

    result = _import(connection, quant_db)

    unreported = repository.list_statements("005930")[0]
    reported = repository.list_statements("000660")[0]
    assert unreported.net_income is None
    assert unreported.sales == 800.0
    assert unreported.operating_income == 100.0
    assert reported.net_income == 60.0
    stored = connection.execute(
        "SELECT typeof(net_income) FROM financial_statements WHERE stock_code = '005930'"
    ).fetchone()[0]
    assert stored == "null"
    assert result.net_income_nullified == 1


def test_import_stores_sales_zero_as_null_but_keeps_other_zero_columns(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [_statement("005930", 2025, sales=0.0, gross_profit=0.0, operating_income=0.0)],
        [],
    )

    result = _import(connection, quant_db)

    saved = repository.list_statements("005930")[0]
    assert saved.sales is None  # 매출 0.0은 NULL
    assert saved.gross_profit == 0.0  # 그 외 0.0은 그대로
    assert saved.operating_income == 0.0
    assert result.sales_nullified == 1


def test_import_rerun_overwrites_stored_net_income_when_source_becomes_unreported(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    first = _make_quant_db(tmp_path / "first.db", [_statement("005930", 2025, net_income=60.0)], [])
    second = _make_quant_db(tmp_path / "second.db", [_statement("005930", 2025, net_income=0.0)], [])

    _import(connection, first)
    _import(connection, second)

    assert repository.list_statements("005930")[0].net_income is None


def test_import_skips_row_when_all_numeric_values_are_null(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    empty = {name: None for name in (
        "assets", "liabilities", "equity", "current_assets", "current_liab",
        "sales", "gross_profit", "operating_income", "net_income",
    )}
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [_statement("005930", 2024, **empty), _statement("005930", 2025)],
        [],
    )

    result = _import(connection, quant_db)

    assert [s.year for s in repository.list_statements("005930")] == [2025]
    assert result.statements_skipped_all_null == 1


# ── 밸류에이션 ──────────────────────────────────────────────────────────


def test_import_upserts_monthly_valuation_into_financial_metrics(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [],
        [_metric("005930", "2026-06"), _metric("005930", "2026-07", per=0.0, pbr=0.0)],
    )

    result = _import(connection, quant_db)

    saved = repository.list_metrics("005930")
    assert [m.year_month for m in saved] == ["2026-06", "2026-07"]
    assert saved[0].close_price == 70000.0
    assert saved[0].per == 12.5
    assert saved[0].trade_date == "2026-06-28"
    assert result.metrics_saved == 2


def test_import_stores_per_and_pbr_zero_as_null_and_keeps_negative_and_other_values(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [],
        [
            _metric("005930", "2026-06", per=0.0, pbr=0.0, psr=0.0),
            _metric("005930", "2026-07", per=-3.2, pbr=0.9),
        ],
    )

    result = _import(connection, quant_db)

    june, july = repository.list_metrics("005930")
    assert june.per is None and june.pbr is None  # 0.0 -> N/A
    assert june.psr == 0.0  # per/pbr 외의 열은 원천 그대로
    assert june.close_price == 70000.0
    assert july.per == -3.2  # 적자 종목의 음수 PER은 유지
    assert july.pbr == 0.9
    stored = connection.execute(
        "SELECT typeof(per) FROM financial_metrics WHERE year_month = '2026-06'"
    ).fetchone()[0]
    assert stored == "null"
    assert result.per_pbr_nullified == 1


def test_import_accepts_alphanumeric_stock_code_when_registered_in_securities(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    # 영문이 섞인 신규 등록 종목코드 (ETF/ETN, 스팩 등)
    SecurityRepository(connection).upsert(
        Security(stock_code="0030R0", name="New listing", market="KOSPI")
    )
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [_statement("0030R0", 2025), _statement("005930", 2025)],
        [_metric("0030R0")],
    )

    result = _import(connection, quant_db)

    assert [s.year for s in repository.list_statements("0030R0")] == [2025]
    assert len(repository.list_metrics("0030R0")) == 1
    assert result.statements_skipped_invalid == 0


def test_import_still_skips_alphanumeric_code_not_in_securities(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(tmp_path / "quant.db", [_statement("0030R0", 2025)], [])

    result = _import(connection, quant_db)

    assert repository.list_statements("0030R0") == []
    assert result.statements_skipped_unknown_code == 1


# ── 검증 / 로그 ─────────────────────────────────────────────────────────


def test_import_skips_unknown_stock_code_and_logs_it(
    connection: sqlite3.Connection,
    repository: FinancialRepository,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [_statement("005930"), _statement("999999")],
        [_metric("005930"), _metric("999999")],
    )

    with caplog.at_level(logging.WARNING):
        result = _import(connection, quant_db)

    assert repository.list_statements("999999") == []
    assert repository.list_metrics("999999") == []
    assert result.statements_skipped_unknown_code == 1
    assert result.metrics_skipped_unknown_code == 1
    assert "999999" in caplog.text
    assert "unknown_stock_code" in caplog.text


def test_parse_statement_rows_rejects_year_out_of_range_and_bad_values() -> None:
    def row(**overrides: object) -> tuple:
        base = _statement("005930", **overrides)
        keys = ("stock_code", "year", "report_type", "assets", "liabilities", "equity",
                "current_assets", "current_liab", "sales", "gross_profit",
                "operating_income", "net_income", "is_consolidated")
        return tuple(base[k] for k in keys)

    stats = StatementParseStats()
    parsed = list(
        parse_statement_rows(
            [
                row(),                                  # 정상
                row(year=1999),                         # 너무 이름
                row(year=CURRENT_YEAR + 1),             # 미래
                row(year="abc"),                        # 정수 아님
                row(assets="N/A"),                      # 숫자 아님
                row(assets=float("nan")),               # NaN
                row(is_consolidated=2),                 # 0/1 아님
                row(report_type="11012"),               # 연간 아님
                ("12345", 2025, "11011") + (1.0,) * 9 + (1,),  # 종목코드 5자리
                ("0030r0", 2025, "11011") + (1.0,) * 9 + (1,),  # 소문자는 허용 안 함
            ],
            {"005930"},
            stats,
            CURRENT_YEAR,
        )
    )

    assert len(parsed) == 1
    assert stats.received == 10
    assert stats.valid == 1
    assert stats.skipped_invalid == 9


def test_parse_metric_rows_rejects_bad_year_month_date_and_negative_price() -> None:
    def row(**overrides: object) -> tuple:
        base = _metric("005930", **overrides)
        keys = ("stock_code", "year_month", "trade_date", "close_price", "market_cap",
                "shares_out", "per", "pbr", "psr", "pcr")
        return tuple(base[k] for k in keys)

    stats = MetricParseStats()
    parsed = list(
        parse_metric_rows(
            [
                row(),                                   # 정상
                row(per=-3.2),                           # 적자 PER은 음수 허용
                row(year_month="2026-13"),               # 없는 월
                row(year_month="202607"),                # 형식 오류
                row(year_month="1999-12"),               # 연도 범위
                row(trade_date="2026-07-99"),            # 없는 날짜
                row(close_price=-1.0),                   # 음수 종가
                row(per="x"),                            # 숫자 아님
                row(trade_date=None),                    # trade_date 없음은 허용
            ],
            {"005930"},
            stats,
            CURRENT_YEAR,
        )
    )

    assert len(parsed) == 3
    assert parsed[1].per == -3.2
    assert parsed[2].trade_date is None
    assert stats.skipped_invalid == 6


# ── 재실행 / 원천 오류 ──────────────────────────────────────────────────


def test_import_rerun_does_not_duplicate_rows_and_updates_changed_values(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    first = _make_quant_db(
        tmp_path / "first.db", [_statement("005930", 2025)], [_metric("005930", "2026-07")]
    )
    second = _make_quant_db(
        tmp_path / "second.db",
        [_statement("005930", 2025, sales=900.0)],
        [_metric("005930", "2026-07", close_price=71000.0)],
    )

    _import(connection, first)
    _import(connection, first)  # 같은 데이터를 다시 가져와도 중복되지 않는다
    assert connection.execute("SELECT COUNT(*) FROM financial_statements").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM financial_metrics").fetchone()[0] == 1

    _import(connection, second)  # 값이 바뀌면 같은 키의 행이 갱신된다
    assert connection.execute("SELECT COUNT(*) FROM financial_statements").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM financial_metrics").fetchone()[0] == 1
    assert repository.list_statements("005930")[0].sales == 900.0
    assert repository.list_metrics("005930")[0].close_price == 71000.0


def test_import_raises_when_quant_db_file_is_missing(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    with pytest.raises(FinancialDataReadError):
        _import(connection, tmp_path / "missing.db")


def test_import_raises_before_writing_when_source_table_is_missing(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.db"
    raw = sqlite3.connect(broken)
    raw.executescript(_SOURCE_SCHEMA.split("CREATE TABLE market_data")[0])  # market_data 없음
    raw.execute("INSERT INTO financial_data (stock_code, year, report_type, assets) "
                "VALUES ('005930', 2025, '11011', 1.0)")
    raw.commit()
    raw.close()

    with pytest.raises(FinancialDataReadError):
        _import(connection, broken)

    assert connection.execute("SELECT COUNT(*) FROM financial_statements").fetchone()[0] == 0


# ── 13 파이프라인 통합 ──────────────────────────────────────────────────


class _FakeSource:
    """ExternalDataSource 대역: 가격은 비어 있고 quant.db는 fixture 파일을 복사한다."""

    def __init__(self, quant_db: Path) -> None:
        self._quant_db = quant_db

    def list_price_stock_codes(self) -> list[str]:
        return []

    def export_prices(self, since_by_code: Mapping[str, str | None], dest_dir: Path) -> PriceExport:
        dest_dir.mkdir(parents=True, exist_ok=True)
        psv = dest_dir / "prices.psv"
        psv.write_text("", encoding="utf-8")
        return PriceExport(psv_path=psv, failures={})

    def fetch_quant_db(self, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / "quant.db"
        shutil.copyfile(self._quant_db, target)
        return target


def test_collect_market_data_also_imports_financial_data_from_same_snapshot(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(tmp_path / "quant_src.db", [_statement("005930", 2025)], [_metric("005930")])
    raw = sqlite3.connect(quant_db)
    raw.executescript(
        "CREATE TABLE stock_master (stock_code TEXT PRIMARY KEY, stock_name TEXT, "
        "corp_code TEXT, market TEXT, updated_at TEXT);"
        "INSERT INTO stock_master VALUES ('005930','Samsung','00126380','KOSPI','2026-10-01');"
    )
    raw.commit()
    raw.close()

    result = collect_market_data(connection, _FakeSource(quant_db), tmp_path / "staging")

    assert result.financial is not None
    assert result.financial.statements_saved == 1
    assert result.financial.metrics_saved == 1
    assert len(repository.list_statements("005930")) == 1
    assert len(repository.list_metrics("005930")) == 1
    assert SecurityRepository(connection).get_by_code("005930").corp_code == "00126380"
