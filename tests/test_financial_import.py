"""Task 014: quant.db 재무/밸류에이션 가져오기 테스트 (fixture 기반, 외부 접속 없음)."""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

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

# 원천 quant.db와 같은 열 구성 (eps, bps, cfo_ytd 포함 - 가져오지 않는지 확인하려고).
# quant_latest가 마지막이어야 한다 (테이블 누락 테스트가 그 앞에서 자른다).
_SOURCE_SCHEMA = """
CREATE TABLE stock (
    code TEXT PRIMARY KEY, name TEXT NOT NULL, asset_type TEXT NOT NULL, market TEXT,
    setl_month INTEGER, corp_code TEXT, is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE daily_price (
    code TEXT NOT NULL, date INTEGER NOT NULL,
    open INTEGER, high INTEGER, low INTEGER, close INTEGER NOT NULL,
    volume INTEGER, value INTEGER,
    PRIMARY KEY (code, date)
) WITHOUT ROWID;
CREATE TABLE share_count (
    code TEXT NOT NULL, asof_date INTEGER NOT NULL, shares INTEGER NOT NULL, src TEXT NOT NULL,
    PRIMARY KEY (code, asof_date)
);
CREATE TABLE financial_q (
    code TEXT NOT NULL, period INTEGER NOT NULL,
    assets INTEGER, current_assets INTEGER, liabilities INTEGER, current_liab INTEGER,
    equity INTEGER,
    revenue_ytd INTEGER, gross_profit_ytd INTEGER, op_income_ytd INTEGER,
    net_income_ytd INTEGER, cfo_ytd INTEGER,
    eps REAL, bps REAL,
    available_date INTEGER NOT NULL, fetched_at INTEGER,
    PRIMARY KEY (code, period)
);
CREATE TABLE corp_event (
    code TEXT NOT NULL, date INTEGER NOT NULL, kind TEXT NOT NULL, ratio REAL, note TEXT,
    PRIMARY KEY (code, date, kind)
);
CREATE VIEW v_adj_price AS SELECT code, date, open, high, low, close, volume, value, adj_factor,
    open * adj_factor AS adj_open, high * adj_factor AS adj_high, low * adj_factor AS adj_low,
    close * adj_factor AS adj_close
FROM (SELECT p.*, COALESCE((SELECT exp(sum(ln(e.ratio))) FROM corp_event e
    WHERE e.code = p.code AND e.date > p.date AND e.ratio > 0
      AND e.kind IN ('REV_SPLIT', 'BONUS', 'CAP_DECREASE')), 1.0) AS adj_factor
FROM daily_price p);
CREATE TABLE quant_latest (
    code TEXT PRIMARY KEY, name TEXT, market_cap INTEGER,
    per REAL, pbr REAL, psr REAL, pcr REAL, roe REAL,
    asof_date INTEGER, fin_period INTEGER
);
"""

# 테스트에서 쓰는 이전 열 이름 -> financial_q 열 이름
_STATEMENT_ALIASES = {
    "sales": "revenue_ytd",
    "gross_profit": "gross_profit_ytd",
    "operating_income": "op_income_ytd",
    "net_income": "net_income_ytd",
}


def _statement(code: str, year: int = 2025, month: int = 12, **overrides: object) -> dict:
    """financial_q 한 행. 기본은 12월 결산 종목의 연간(12월 분기) 누적 값."""
    row = {
        "code": code, "period": year * 100 + month,
        "assets": 1000.0, "liabilities": 400.0, "equity": 600.0,
        "current_assets": 500.0, "current_liab": 300.0,
        "revenue_ytd": 800.0, "gross_profit_ytd": 200.0, "op_income_ytd": 100.0,
        "net_income_ytd": 60.0, "cfo_ytd": 11.0, "eps": 0.0, "bps": 0.0,
        "available_date": year * 10000 + 331,
    }
    row.update({_STATEMENT_ALIASES.get(key, key): value for key, value in overrides.items()})
    return row


def _metric(code: str, year_month: str = "2026-07", **overrides: object) -> dict:
    """quant_latest 한 행 + 그날 종가(daily_price)와 주식수(share_count)."""
    row = {
        "code": code, "asof_date": int(year_month.replace("-", "") + "28"),
        "close_price": 70000.0, "market_cap": 4.2e14, "shares_out": 6.0e9,
        "per": 12.5, "pbr": 1.4, "psr": 1.1, "pcr": 5.0,
    }
    row.update(overrides)
    return row


def _insert(connection: sqlite3.Connection, table: str, row: dict) -> None:
    columns = ", ".join(row)
    marks = ", ".join(f":{name}" for name in row)
    connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", row)


def _make_quant_db(
    path: Path,
    statements: list[dict],
    metrics: list[dict],
    setl_months: dict[str, int | None] | None = None,
    corp_codes: dict[str, str] | None = None,
) -> Path:
    setl_months = setl_months or {}
    corp_codes = corp_codes or {}
    codes = {row["code"] for row in statements + metrics} | set(setl_months) | set(corp_codes)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SOURCE_SCHEMA)
        for code in sorted(codes):
            _insert(connection, "stock", {
                "code": code, "name": code, "asset_type": "STOCK", "market": "STK",
                "setl_month": setl_months.get(code, 12), "corp_code": corp_codes.get(code),
            })
        for row in statements:
            _insert(connection, "financial_q", row)
        for row in metrics:
            quant = dict(row)
            close_price = quant.pop("close_price")
            shares_out = quant.pop("shares_out")
            _insert(connection, "quant_latest", quant)
            if close_price is not None:
                _insert(connection, "daily_price", {
                    "code": row["code"], "date": row["asof_date"], "open": close_price,
                    "high": close_price, "low": close_price, "close": close_price,
                    "volume": 1000,
                })
            if shares_out is not None:
                _insert(connection, "share_count", {
                    "code": row["code"], "asof_date": row["asof_date"] - 5,
                    "shares": shares_out, "src": "daily",
                })
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


def test_import_uses_only_fiscal_year_end_quarter_as_annual_statement(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [
            _statement("005930", 2025, 3, sales=200.0),
            _statement("005930", 2025, 6, sales=400.0),
            _statement("005930", 2025, 9, sales=600.0),
            _statement("005930", 2025, 12, sales=800.0),
            # 3월 결산 종목: 2026년 3월 분기가 연간이다
            _statement("000660", 2025, 12, sales=750.0),
            _statement("000660", 2026, 3, sales=1000.0),
        ],
        [],
        setl_months={"000660": 3},
    )

    _import(connection, quant_db)

    december = repository.list_statements("005930")
    assert [(s.year, s.report_type, s.sales) for s in december] == [(2025, "11011", 800.0)]
    march = repository.list_statements("000660")
    assert [(s.year, s.sales) for s in march] == [(2026, 1000.0)]


def test_import_treats_missing_fiscal_month_as_december(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [_statement("005930", 2025, 9), _statement("005930", 2025, 12)],
        [],
        setl_months={"005930": None},
    )

    _import(connection, quant_db)

    assert [s.year for s in repository.list_statements("005930")] == [2025]


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


def test_import_upserts_latest_valuation_as_month_row_and_keeps_previous_months(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    june = _make_quant_db(tmp_path / "june.db", [], [_metric("005930", "2026-06")])
    july = _make_quant_db(
        tmp_path / "july.db", [], [_metric("005930", "2026-07", close_price=71000.0)]
    )

    _import(connection, june)
    result = _import(connection, july)

    saved = repository.list_metrics("005930")
    assert [m.year_month for m in saved] == ["2026-06", "2026-07"]
    assert saved[0].close_price == 70000.0
    assert saved[0].trade_date == "2026-06-28"
    assert saved[1].close_price == 71000.0  # asof_date의 daily_price 종가
    assert saved[1].shares_out == 6.0e9  # asof_date 이전 가장 최근 share_count
    assert saved[1].market_cap == 4.2e14
    assert saved[1].per == 12.5
    assert result.metrics_saved == 1


def test_import_stores_per_and_pbr_zero_as_null_and_keeps_negative_and_other_values(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [],
        [
            _metric("005930", per=0.0, pbr=0.0, psr=0.0),
            _metric("000660", per=-3.2, pbr=0.9),
        ],
    )

    result = _import(connection, quant_db)

    zero = repository.list_metrics("005930")[0]
    negative = repository.list_metrics("000660")[0]
    assert zero.per is None and zero.pbr is None  # 0.0 -> N/A
    assert zero.psr == 0.0  # per/pbr 외의 열은 원천 그대로
    assert zero.close_price == 70000.0
    assert negative.per == -3.2  # 적자 종목의 음수 PER은 유지
    assert negative.pbr == 0.9
    stored = connection.execute(
        "SELECT typeof(per) FROM financial_metrics WHERE stock_code = '005930'"
    ).fetchone()[0]
    assert stored == "null"
    assert result.per_pbr_nullified == 1


def test_import_keeps_valuation_when_close_price_is_missing(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(tmp_path / "quant.db", [], [_metric("005930", close_price=None)])

    _import(connection, quant_db)

    saved = repository.list_metrics("005930")[0]
    assert saved.close_price is None
    assert saved.per == 12.5


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
        base = {
            "stock_code": "005930", "year": 2025, "report_type": "11011",
            "assets": 1000.0, "liabilities": 400.0, "equity": 600.0,
            "current_assets": 500.0, "current_liab": 300.0, "sales": 800.0,
            "gross_profit": 200.0, "operating_income": 100.0, "net_income": 60.0,
            "is_consolidated": 1,
        }
        base.update(overrides)
        return tuple(base.values())

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
        base = {
            "stock_code": "005930", "year_month": "2026-07", "trade_date": "2026-07-28",
            "close_price": 70000.0, "market_cap": 4.2e14, "shares_out": 6.0e9,
            "per": 12.5, "pbr": 1.4, "psr": 1.1, "pcr": 5.0,
        }
        base.update(overrides)
        return tuple(base.values())

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
    raw.executescript(_SOURCE_SCHEMA.split("CREATE TABLE quant_latest")[0])  # quant_latest 없음
    raw.execute("INSERT INTO financial_q (code, period, assets, available_date) "
                "VALUES ('005930', 202512, 1.0, 20260331)")
    raw.commit()
    raw.close()

    with pytest.raises(FinancialDataReadError):
        _import(connection, broken)

    assert connection.execute("SELECT COUNT(*) FROM financial_statements").fetchone()[0] == 0


# ── 13 파이프라인 통합 ──────────────────────────────────────────────────


class _FakeSource:
    """ExternalDataSource 대역: quant.db는 fixture 파일을 복사한다."""

    def __init__(self, quant_db: Path) -> None:
        self._quant_db = quant_db

    def fetch_quant_db(self, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / "quant.db"
        shutil.copyfile(self._quant_db, target)
        return target


def test_collect_market_data_imports_prices_corp_codes_and_financials_from_one_snapshot(
    connection: sqlite3.Connection, repository: FinancialRepository, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant_src.db",
        [_statement("005930", 2025)],
        [_metric("005930")],
        corp_codes={"005930": "00126380"},
    )

    result = collect_market_data(connection, _FakeSource(quant_db), tmp_path / "staging")

    assert result.prices.rows_saved == 1  # _metric이 넣은 asof_date 종가 1행
    assert result.financial is not None
    assert result.financial.statements_saved == 1
    assert result.financial.metrics_saved == 1
    assert len(repository.list_statements("005930")) == 1
    assert len(repository.list_metrics("005930")) == 1
    assert SecurityRepository(connection).get_by_code("005930").corp_code == "00126380"
