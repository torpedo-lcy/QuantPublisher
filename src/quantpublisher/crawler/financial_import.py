"""quant.db의 연간 재무제표/최신 밸류에이션을 가져와 저장한다 (Task 014).

외부 Mac에서 ``.backup``으로 만든 quant.db 스냅샷(Task 013의 복사 경로)을 로컬에서
읽기 전용으로 열어 가져온다.

    financial_q (결산월 분기만) -> 파싱/검증 -> financial_statements upsert
    quant_latest (+ daily_price 종가, share_count 주식수) -> 파싱/검증 -> financial_metrics upsert

단계 분리 (price_import.py와 같은 방식):
    parse_statement_rows / parse_metric_rows : 행 검증/변환 (순수 함수)
    save_statements / save_metrics           : Repository를 통한 배치 upsert
    import_financial_data                    : 위 단계를 잇는 진입점

원천 변환 규칙:
    * financial_q는 분기(period=YYYYMM) 누적(YTD) 값이다. period의 월이 그 종목의
      결산월(stock.setl_month, 없으면 12)인 행만 연간 재무제표로 보고, year는 period의
      연도, report_type은 '11011'(연간)로 저장한다. *_ytd 열이 연간 값이 된다.
    * financial_q에는 연결/별도 구분이 없다. 모두 연결(is_consolidated=1)로 저장한다.
      사용자 결정 (2026-10-26). 매출성장률이 연결/별도 비교로 N/A가 되지 않게 하려는 것이다.
    * quant_latest는 종목별 최신 1행이다. asof_date의 월을 year_month로 해서
      financial_metrics에 upsert한다 (실행할 때마다 그 달의 행이 갱신되고, 지난 달 행은
      그대로 남는다). 사용자 결정 (2026-10-26). close_price는 asof_date의 daily_price
      종가, shares_out은 asof_date 이전 가장 최근 share_count 값이다.
    * quant_latest의 per/psr/pcr은 최근 4분기(TTM) 기준이다. 이전 원천(market_data)은
      직전 연간 기준이어서 같은 종목이라도 값이 다를 수 있다.

데이터 처리 규칙:
    * financial_q의 eps/bps/cfo_ytd는 가져오지 않는다 (EPS/BPS는 Task 015에서 종가와
      PER/PBR로 역산한다).
    * net_income == 0.0은 "미공시"로 간주해 NULL로 저장한다. DART 잠정실적 공시가
      순이익 없이 먼저 올라오는 경우가 많아, 0을 그대로 저장하면 ROE 등이 0%로
      잘못 계산되기 때문이다.
    * sales == 0.0도 같은 이유로 NULL로 저장한다 (영업이익률/순이익률/매출성장률이
      0 나눗셈이나 잘못된 값이 되는 것을 막는다). 사용자 결정 (2026-10-09).
    * per == 0.0, pbr == 0.0은 "계산 불가"로 보고 NULL(=N/A)로 저장한다.
      PER/PBR 0은 실제 값일 수 없다. 사용자 결정 (2026-10-09).
      psr/pcr 등 다른 열은 원천 값 그대로 저장한다.
    * 종목코드는 숫자 또는 영문 대문자 6자리를 허용한다 (ETF/ETN 등 신규 코드).
      단, securities에 등록된 종목만 저장한다.
    * 위 외의 0.0(gross_profit, operating_income 등)은 그대로 저장한다.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Iterator

from quantpublisher.database.financial_repository import FinancialRepository
from quantpublisher.database.models import FinancialMetric, FinancialStatement
from quantpublisher.database.security_repository import SecurityRepository
from quantpublisher.database.stock_code import STOCK_CODE_PATTERN

logger = logging.getLogger(__name__)

ANNUAL_REPORT_TYPE = "11011"
MIN_YEAR = 2000

_YEAR_MONTH_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BATCH_SIZE = 50_000
_FETCH_SIZE = 10_000
_LOG_SAMPLE_SIZE = 10

# 파서가 받는 행의 열 순서 (원천 쿼리가 이 순서로 열을 만든다).
_STATEMENT_COLUMNS = (
    "stock_code",
    "year",
    "report_type",
    "assets",
    "liabilities",
    "equity",
    "current_assets",
    "current_liab",
    "sales",
    "gross_profit",
    "operating_income",
    "net_income",
    "is_consolidated",
)
_STATEMENT_AMOUNT_COUNT = 9  # assets ~ net_income (is_consolidated 제외)
# 금액 열(row[3:12]) 안에서 net_income의 위치
_NET_INCOME_AMOUNT_INDEX = _STATEMENT_COLUMNS.index("net_income") - 3
_SALES_AMOUNT_INDEX = _STATEMENT_COLUMNS.index("sales") - 3

_METRIC_COLUMNS = (
    "stock_code",
    "year_month",
    "trade_date",
    "close_price",
    "market_cap",
    "shares_out",
    "per",
    "pbr",
    "psr",
    "pcr",
)
# financial_q에서 결산월 분기를 연간 재무제표 행(_STATEMENT_COLUMNS 순서)으로 읽는다.
# 결산월이 없는 종목은 12월로 본다. 연결/별도 구분이 없어 모두 연결(1)로 둔다.
_STATEMENT_QUERY = f"""
SELECT f.code, f.period / 100, '{ANNUAL_REPORT_TYPE}',
       f.assets, f.liabilities, f.equity, f.current_assets, f.current_liab,
       f.revenue_ytd, f.gross_profit_ytd, f.op_income_ytd, f.net_income_ytd,
       1
FROM financial_q AS f
LEFT JOIN stock AS s ON s.code = f.code
WHERE f.period % 100 = COALESCE(s.setl_month, 12)
"""

# quant_latest를 최신 월 밸류에이션 행(_METRIC_COLUMNS 순서)으로 읽는다.
_METRIC_QUERY = """
SELECT q.code,
       substr(q.asof_date, 1, 4) || '-' || substr(q.asof_date, 5, 2),
       substr(q.asof_date, 1, 4) || '-' || substr(q.asof_date, 5, 2) || '-'
           || substr(q.asof_date, 7, 2),
       d.close,
       q.market_cap,
       (SELECT sc.shares FROM share_count AS sc
         WHERE sc.code = q.code AND sc.asof_date <= q.asof_date
         ORDER BY sc.asof_date DESC LIMIT 1),
       q.per, q.pbr, q.psr, q.pcr
FROM quant_latest AS q
LEFT JOIN daily_price AS d ON d.code = q.code AND d.date = q.asof_date
"""

# 원천 쿼리가 읽는 테이블과 열 (DB 쓰기 전에 존재를 확인한다).
_SOURCE_COLUMNS = {
    "financial_q": (
        "code", "period", "assets", "liabilities", "equity", "current_assets",
        "current_liab", "revenue_ytd", "gross_profit_ytd", "op_income_ytd", "net_income_ytd",
    ),
    "stock": ("code", "setl_month"),
    "quant_latest": ("code", "asof_date", "market_cap", "per", "pbr", "psr", "pcr"),
    "daily_price": ("code", "date", "close"),
    "share_count": ("code", "asof_date", "shares"),
}

_METRIC_NON_NEGATIVE_COUNT = 3  # close_price, market_cap, shares_out
# 숫자 열(row[3:10]) 안에서 0.0을 NULL(N/A)로 바꾸는 열: per, pbr
_METRIC_ZERO_AS_NULL_INDEXES = (
    _METRIC_COLUMNS.index("per") - 3,
    _METRIC_COLUMNS.index("pbr") - 3,
)


class FinancialDataReadError(Exception):
    """quant.db의 financial_q/quant_latest 등을 읽을 수 없을 때의 오류."""


@dataclass(slots=True)
class StatementParseStats:
    """재무제표 파싱 중 집계되는 건수 (parse_statement_rows가 채운다)."""

    received: int = 0
    valid: int = 0
    skipped_unknown_code: int = 0
    skipped_invalid: int = 0
    skipped_all_null: int = 0
    net_income_nullified: int = 0
    sales_nullified: int = 0
    unknown_codes: set[str] = field(default_factory=set)


@dataclass(slots=True)
class MetricParseStats:
    """밸류에이션 파싱 중 집계되는 건수 (parse_metric_rows가 채운다)."""

    received: int = 0
    valid: int = 0
    skipped_unknown_code: int = 0
    skipped_invalid: int = 0
    skipped_all_null: int = 0
    per_pbr_nullified: int = 0
    unknown_codes: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class FinancialImportResult:
    """재무/밸류에이션 가져오기 결과.

    Attributes:
        statements_received: 읽은 연간 재무제표 행 수.
        statements_saved: financial_statements에 upsert한 행 수.
        statements_skipped_unknown_code: securities에 없는 종목코드라 건너뛴 행 수.
        statements_skipped_invalid: 형식/범위 검증 실패로 건너뛴 행 수.
        statements_skipped_all_null: 숫자 값이 전부 비어 건너뛴 행 수.
        net_income_nullified: net_income 0.0을 NULL(미공시)로 바꿔 저장한 행 수.
        sales_nullified: sales 0.0을 NULL로 바꿔 저장한 행 수.
        metrics_received: 읽은 월별 밸류에이션 행 수.
        metrics_saved: financial_metrics에 upsert한 행 수.
        metrics_skipped_unknown_code: securities에 없는 종목코드라 건너뛴 행 수.
        metrics_skipped_invalid: 형식/범위 검증 실패로 건너뛴 행 수.
        metrics_skipped_all_null: 숫자 값이 전부 비어 건너뛴 행 수.
        per_pbr_nullified: per/pbr 0.0을 NULL(N/A)로 바꿔 저장한 행 수.
    """

    statements_received: int
    statements_saved: int
    statements_skipped_unknown_code: int
    statements_skipped_invalid: int
    statements_skipped_all_null: int
    net_income_nullified: int
    sales_nullified: int
    metrics_received: int
    metrics_saved: int
    metrics_skipped_unknown_code: int
    metrics_skipped_invalid: int
    metrics_skipped_all_null: int
    per_pbr_nullified: int


# ── 파싱/검증 (순수 함수) ────────────────────────────────────────────────


def parse_statement_rows(
    rows: Iterable[tuple[Any, ...]],
    known_codes: set[str],
    stats: StatementParseStats,
    current_year: int,
) -> Iterator[FinancialStatement]:
    """연간 재무제표 행(_STATEMENT_COLUMNS 순서)을 검증해 FinancialStatement로 변환한다.

    다음 행은 건너뛰고 stats에 센다 (조용히 버리지 않는다):
        - 종목코드가 숫자/영문 대문자 6자리가 아님 / year가 정수가 아니거나 [MIN_YEAR, current_year]
          밖 / report_type이 '11011'이 아님 / 값이 있는데 숫자가 아님(NaN/inf 포함) /
          is_consolidated가 0, 1, 비어 있음 중 하나가 아님 -> invalid
        - securities(known_codes)에 없는 종목코드 -> unknown_code
        - 숫자 값이 전부 비어 있음 -> all_null

    net_income, sales가 0.0이면 "미공시"로 보고 None으로 바꾼다 (모듈 설명 참고).
    그 외의 0.0은 그대로 둔다.
    """
    for row in rows:
        stats.received += 1
        raw_code = row[0]
        stock_code = str(raw_code).strip() if raw_code is not None else ""
        if not STOCK_CODE_PATTERN.match(stock_code):
            stats.skipped_invalid += 1
            continue
        if stock_code not in known_codes:
            stats.skipped_unknown_code += 1
            stats.unknown_codes.add(stock_code)
            continue

        year = _to_year(row[1], current_year)
        report_type = str(row[2]).strip() if row[2] is not None else ""
        if year is None or report_type != ANNUAL_REPORT_TYPE:
            stats.skipped_invalid += 1
            continue

        amounts = [_to_float(value) for value in row[3 : 3 + _STATEMENT_AMOUNT_COUNT]]
        if any(parsed is _INVALID for parsed in amounts):
            stats.skipped_invalid += 1
            continue
        is_consolidated = _to_flag(row[3 + _STATEMENT_AMOUNT_COUNT])
        if is_consolidated is _INVALID:
            stats.skipped_invalid += 1
            continue

        # net_income == 0.0 은 '미공시'다 -> NULL로 저장한다 (0%로 계산되는 것을 막는다).
        # sales == 0.0 도 같은 이유로 NULL로 저장한다.
        nullified = amounts[_NET_INCOME_AMOUNT_INDEX] == 0.0
        if nullified:
            amounts[_NET_INCOME_AMOUNT_INDEX] = None
        sales_nullified = amounts[_SALES_AMOUNT_INDEX] == 0.0
        if sales_nullified:
            amounts[_SALES_AMOUNT_INDEX] = None
        if all(value is None for value in amounts):
            stats.skipped_all_null += 1
            continue

        stats.valid += 1
        if nullified:
            stats.net_income_nullified += 1
        if sales_nullified:
            stats.sales_nullified += 1
        (
            assets,
            liabilities,
            equity,
            current_assets,
            current_liab,
            sales,
            gross_profit,
            operating_income,
            net_income,
        ) = amounts
        yield FinancialStatement(
            stock_code=stock_code,
            year=year,
            report_type=report_type,
            assets=assets,
            liabilities=liabilities,
            equity=equity,
            current_assets=current_assets,
            current_liab=current_liab,
            sales=sales,
            gross_profit=gross_profit,
            operating_income=operating_income,
            net_income=net_income,
            is_consolidated=is_consolidated,
        )


def parse_metric_rows(
    rows: Iterable[tuple[Any, ...]],
    known_codes: set[str],
    stats: MetricParseStats,
    current_year: int,
) -> Iterator[FinancialMetric]:
    """밸류에이션 행(_METRIC_COLUMNS 순서)을 검증해 FinancialMetric으로 변환한다.

    다음 행은 건너뛰고 stats에 센다 (조용히 버리지 않는다):
        - 종목코드가 숫자/영문 대문자 6자리가 아님 / year_month가 실제 YYYY-MM이 아니거나 연도가
          [MIN_YEAR, current_year] 밖 / trade_date가 있는데 실제 YYYY-MM-DD가 아님 /
          값이 있는데 숫자가 아님 / 종가·시가총액·상장주식수가 음수 -> invalid
        - securities(known_codes)에 없는 종목코드 -> unknown_code
        - 숫자 값이 전부 비어 있음 -> all_null

    per/pbr이 0.0이면 "계산 불가"로 보고 None(=N/A)으로 바꾼다. 적자 종목의 음수
    per/pbr과 psr/pcr은 원천 값 그대로 저장한다.
    """
    for row in rows:
        stats.received += 1
        raw_code = row[0]
        stock_code = str(raw_code).strip() if raw_code is not None else ""
        if not STOCK_CODE_PATTERN.match(stock_code):
            stats.skipped_invalid += 1
            continue
        if stock_code not in known_codes:
            stats.skipped_unknown_code += 1
            stats.unknown_codes.add(stock_code)
            continue

        year_month = _to_year_month(row[1], current_year)
        trade_date = _to_optional_date(row[2])
        if year_month is None or trade_date is _INVALID:
            stats.skipped_invalid += 1
            continue

        numbers = [_to_float(value) for value in row[3:10]]
        if any(parsed is _INVALID for parsed in numbers):
            stats.skipped_invalid += 1
            continue
        if any(
            value is not None and value < 0 for value in numbers[:_METRIC_NON_NEGATIVE_COUNT]
        ):
            stats.skipped_invalid += 1
            continue
        zero_nullified = False
        for index in _METRIC_ZERO_AS_NULL_INDEXES:
            if numbers[index] == 0.0:
                numbers[index] = None
                zero_nullified = True
        if all(value is None for value in numbers):
            stats.skipped_all_null += 1
            continue

        stats.valid += 1
        if zero_nullified:
            stats.per_pbr_nullified += 1
        close_price, market_cap, shares_out, per, pbr, psr, pcr = numbers
        yield FinancialMetric(
            stock_code=stock_code,
            year_month=year_month,
            trade_date=trade_date,
            close_price=close_price,
            market_cap=market_cap,
            shares_out=shares_out,
            per=per,
            pbr=pbr,
            psr=psr,
            pcr=pcr,
        )


# ── 저장 ────────────────────────────────────────────────────────────────


def save_statements(
    connection: sqlite3.Connection, statements: Iterable[FinancialStatement]
) -> int:
    """재무제표를 배치 단위로 upsert한다. 배치마다 하나의 트랜잭션이다."""
    repository = FinancialRepository(connection)
    iterator = iter(statements)
    total = 0
    while batch := list(islice(iterator, _BATCH_SIZE)):
        total += repository.upsert_statements(batch)
    logger.info("financial_statements_saved count=%d", total)
    return total


def save_metrics(connection: sqlite3.Connection, metrics: Iterable[FinancialMetric]) -> int:
    """밸류에이션을 배치 단위로 upsert한다. 배치마다 하나의 트랜잭션이다."""
    repository = FinancialRepository(connection)
    iterator = iter(metrics)
    total = 0
    while batch := list(islice(iterator, _BATCH_SIZE)):
        total += repository.upsert_metrics(batch)
    logger.info("financial_metrics_saved count=%d", total)
    return total


# ── 진입점 ──────────────────────────────────────────────────────────────


def import_financial_data(
    connection: sqlite3.Connection,
    quant_db_path: Path,
    current_year: int | None = None,
) -> FinancialImportResult:
    """quant.db 스냅샷에서 연간 재무제표와 최신 밸류에이션을 가져온다 (idempotent).

    quant.db는 읽기 전용으로만 연다. 원천 테이블/열 확인은 DB 쓰기보다 먼저 끝나므로,
    읽을 수 없으면 financial_* 테이블은 바뀌지 않는다.

    Args:
        connection: QuantPublisher DB connection.
        quant_db_path: 로컬로 복사한 quant.db 스냅샷.
        current_year: year 검증 상한. None이면 올해.

    Raises:
        FinancialDataReadError: 파일이 없거나 테이블/열을 읽을 수 없는 경우.
    """
    upper_year = current_year if current_year is not None else date.today().year
    known_codes = {s.stock_code for s in SecurityRepository(connection).list_all()}
    _check_source_schema(quant_db_path)

    statement_stats = StatementParseStats()
    statements = parse_statement_rows(
        _read_rows(quant_db_path, _STATEMENT_QUERY),
        known_codes,
        statement_stats,
        upper_year,
    )
    statements_saved = save_statements(connection, statements)
    _log_skips("financial_statements", statement_stats)

    metric_stats = MetricParseStats()
    metrics = parse_metric_rows(
        _read_rows(quant_db_path, _METRIC_QUERY),
        known_codes,
        metric_stats,
        upper_year,
    )
    metrics_saved = save_metrics(connection, metrics)
    _log_skips("financial_metrics", metric_stats)

    logger.info(
        "financial_data_imported statements_received=%d statements_saved=%d "
        "net_income_nullified=%d sales_nullified=%d metrics_received=%d metrics_saved=%d "
        "per_pbr_nullified=%d",
        statement_stats.received,
        statements_saved,
        statement_stats.net_income_nullified,
        statement_stats.sales_nullified,
        metric_stats.received,
        metrics_saved,
        metric_stats.per_pbr_nullified,
    )
    return FinancialImportResult(
        statements_received=statement_stats.received,
        statements_saved=statements_saved,
        statements_skipped_unknown_code=statement_stats.skipped_unknown_code,
        statements_skipped_invalid=statement_stats.skipped_invalid,
        statements_skipped_all_null=statement_stats.skipped_all_null,
        net_income_nullified=statement_stats.net_income_nullified,
        sales_nullified=statement_stats.sales_nullified,
        metrics_received=metric_stats.received,
        metrics_saved=metrics_saved,
        metrics_skipped_unknown_code=metric_stats.skipped_unknown_code,
        metrics_skipped_invalid=metric_stats.skipped_invalid,
        metrics_skipped_all_null=metric_stats.skipped_all_null,
        per_pbr_nullified=metric_stats.per_pbr_nullified,
    )


# ── 내부 구현 ───────────────────────────────────────────────────────────


class _Invalid:
    """값이 있는데 변환할 수 없음을 나타내는 표식 (None=비어 있음과 구분한다)."""

    def __repr__(self) -> str:
        return "<invalid>"


_INVALID: Any = _Invalid()


def _to_float(value: Any) -> float | None | _Invalid:
    """None -> None(결측). 숫자(문자열 포함) -> float. 그 외/NaN/inf -> _INVALID."""
    if value is None:
        return None
    if isinstance(value, bool):
        return _INVALID
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return _INVALID
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        return _INVALID
    if not math.isfinite(number):
        return _INVALID
    return number


def _to_year(value: Any, current_year: int) -> int | None:
    """정수 연도이고 [MIN_YEAR, current_year] 안이면 int, 아니면 None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            return None
        value = int(text)
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    if not isinstance(value, int):
        return None
    if value < MIN_YEAR or value > current_year:
        return None
    return value


def _to_flag(value: Any) -> int | None | _Invalid:
    """is_consolidated: None -> None, 0/1 -> int, 그 외 -> _INVALID."""
    if value is None:
        return None
    if isinstance(value, bool):
        return _INVALID
    if isinstance(value, (int, float)) and value in (0, 1):
        return int(value)
    return _INVALID


def _to_year_month(value: Any, current_year: int) -> str | None:
    """실제 YYYY-MM이고 연도가 범위 안이면 그대로, 아니면 None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    match = _YEAR_MONTH_PATTERN.match(text)
    if match is None:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12 or year < MIN_YEAR or year > current_year:
        return None
    return text


def _to_optional_date(value: Any) -> str | None | _Invalid:
    """trade_date: None/빈 문자열 -> None, 실제 YYYY-MM-DD -> 그대로, 그 외 -> _INVALID."""
    if value is None:
        return None
    if not isinstance(value, str):
        return _INVALID
    text = value.strip()
    if not text:
        return None
    if not _DATE_PATTERN.match(text):
        return _INVALID
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return _INVALID
    return text


def _check_source_schema(quant_db_path: Path) -> None:
    """원천 테이블과 필요한 열이 있는지 DB 쓰기 전에 확인한다."""
    if not quant_db_path.exists():
        raise FinancialDataReadError(f"quant.db 파일이 없습니다: {quant_db_path}")
    try:
        connection = sqlite3.connect(f"file:{quant_db_path}?mode=ro", uri=True)
        try:
            for table, columns in _SOURCE_COLUMNS.items():
                existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                if not existing:
                    raise FinancialDataReadError(f"quant.db에 {table} 테이블이 없습니다.")
                missing = [column for column in columns if column not in existing]
                if missing:
                    raise FinancialDataReadError(
                        f"quant.db {table}에 필요한 열이 없습니다: {', '.join(missing)}"
                    )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise FinancialDataReadError(f"quant.db 확인 실패: {exc}") from exc


def _read_rows(quant_db_path: Path, query: str) -> Iterator[tuple[Any, ...]]:
    """quant.db를 읽기 전용으로 열어 행을 스트리밍한다 (전체를 메모리에 올리지 않는다)."""
    try:
        connection = sqlite3.connect(f"file:{quant_db_path}?mode=ro", uri=True)
        try:
            cursor = connection.execute(query)
            while chunk := cursor.fetchmany(_FETCH_SIZE):
                yield from chunk
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise FinancialDataReadError(f"quant.db 읽기 실패: {exc}") from exc


def _log_skips(table: str, stats: StatementParseStats | MetricParseStats) -> None:
    """건너뛴 행이 있으면 건수와 종목코드 예시를 로그에 남긴다."""
    if stats.skipped_unknown_code:
        logger.warning(
            "%s_unknown_stock_code skipped rows=%d codes=%d sample=%s",
            table,
            stats.skipped_unknown_code,
            len(stats.unknown_codes),
            sorted(stats.unknown_codes)[:_LOG_SAMPLE_SIZE],
        )
    if stats.skipped_invalid or stats.skipped_all_null:
        logger.warning(
            "%s_rows_skipped invalid=%d all_null=%d",
            table,
            stats.skipped_invalid,
            stats.skipped_all_null,
        )
