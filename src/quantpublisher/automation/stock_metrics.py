"""저장된 재무/밸류에이션 데이터를 지표 계산 함수에 연결한다 (Task 015).

이 모듈은 계산식을 새로 만들지 않는다. financial_statements /
financial_metrics에서 필요한 값을 골라 quantpublisher.analysis.metrics의
계산 함수에 전달하고, 결과를 StockMetrics와 MetricsBasis로 묶는 연결
역할만 담당한다.

- 조회(load_stock_metrics): FinancialRepository로 한 종목의 행을 읽는다.
- 선택/전달(compute_stock_metrics): DB에 접근하지 않는 순수 함수다.

지표별 산출 방식 (docs/TASKS/015_report_metrics.md):
    ROE, ROA, 영업이익률, 순이익률, 부채비율 : 최신 연간 재무제표
    매출성장률 : 최신 연도와 바로 전 연도(year - 1)의 sales. 전년도가 없거나
                연결/별도 기준이 두 연도에서 다르면 None
    PER, PBR  : 최신 월 financial_metrics 값을 그대로 사용 (재계산하지 않음)
    EPS, BPS  : close_price / per, close_price / pbr (per/pbr이 없거나 0이면 None)
    배당수익률 : 데이터 없음. 항상 None
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Sequence

from quantpublisher.analysis.metrics import (
    calculate_debt_ratio,
    calculate_net_margin,
    calculate_operating_margin,
    calculate_revenue_growth_rate,
    calculate_roa,
    calculate_roe,
)
from quantpublisher.database.financial_repository import FinancialRepository
from quantpublisher.database.models import FinancialMetric, FinancialStatement
from quantpublisher.report import MetricsBasis, StockMetrics

logger = logging.getLogger(__name__)

# 연간 사업보고서 report_type (DART). financial_statements에는 이 값만 저장된다.
ANNUAL_REPORT_TYPE = "11011"


def load_stock_metrics(
    connection: sqlite3.Connection, stock_code: str
) -> tuple[StockMetrics, MetricsBasis]:
    """한 종목의 재무/밸류에이션 데이터를 조회해 지표를 계산한다.

    데이터가 없으면 해당 지표는 None(페이지에서 N/A)이다. DB 오류
    (sqlite3.Error)는 숨기지 않고 호출자에게 전달한다.
    """
    repository = FinancialRepository(connection)
    statements = repository.list_statements(stock_code)
    valuations = repository.list_metrics(stock_code)
    latest_valuation = valuations[-1] if valuations else None
    return compute_stock_metrics(statements, latest_valuation)


def compute_stock_metrics(
    statements: Sequence[FinancialStatement],
    latest_valuation: FinancialMetric | None,
) -> tuple[StockMetrics, MetricsBasis]:
    """재무제표 목록과 최신 월 밸류에이션으로 StockMetrics와 기준 정보를 만든다.

    Args:
        statements: 한 종목의 재무제표 행 (순서 무관). 연간(11011)이 아닌 행은 무시한다.
        latest_valuation: 한 종목의 가장 최근 월 financial_metrics 행. 없으면 None.

    Returns:
        (StockMetrics, MetricsBasis). 기준 데이터가 없으면 MetricsBasis 해당 필드는 None.
    """
    annual = _annual_statements_by_year(statements)
    latest = annual[max(annual)] if annual else None
    previous = annual.get(latest.year - 1) if latest is not None else None

    statement_values = _statement_metrics(latest, previous)
    valuation_values = _valuation_metrics(latest_valuation)
    metrics = StockMetrics(
        **statement_values,
        **valuation_values,
        dividend_yield=None,  # 배당 데이터 없음 (Task 015 범위 밖)
    )
    basis = MetricsBasis(
        statement_year=latest.year if latest is not None else None,
        is_consolidated=latest.is_consolidated if latest is not None else None,
        valuation_month=latest_valuation.year_month if latest_valuation is not None else None,
    )
    return metrics, basis


def _annual_statements_by_year(
    statements: Sequence[FinancialStatement],
) -> dict[int, FinancialStatement]:
    """연간(11011) 재무제표만 골라 연도별로 정리한다."""
    return {s.year: s for s in statements if s.report_type == ANNUAL_REPORT_TYPE}


def _statement_metrics(
    latest: FinancialStatement | None,
    previous: FinancialStatement | None,
) -> dict[str, float | None]:
    """최신 연간 재무제표(및 전년도)로 재무 지표를 계산한다.

    전년도 행이 없거나 연결/별도 기준이 다르면 previous_revenue에 None을 넘겨
    매출성장률이 None이 되게 한다 (임의로 추정하지 않는다).
    """
    if latest is None:
        return {
            "roe": None,
            "roa": None,
            "operating_margin": None,
            "net_margin": None,
            "debt_ratio": None,
            "revenue_growth_rate": None,
        }
    previous_sales = previous.sales if _is_comparable(latest, previous) else None
    return {
        "roe": calculate_roe(latest.net_income, latest.equity),
        "roa": calculate_roa(latest.net_income, latest.assets),
        "operating_margin": calculate_operating_margin(latest.operating_income, latest.sales),
        "net_margin": calculate_net_margin(latest.net_income, latest.sales),
        "debt_ratio": calculate_debt_ratio(latest.liabilities, latest.equity),
        "revenue_growth_rate": calculate_revenue_growth_rate(latest.sales, previous_sales),
    }


def _is_comparable(
    latest: FinancialStatement, previous: FinancialStatement | None
) -> bool:
    """전년도 행이 있고 두 연도의 연결/별도 기준이 충돌하지 않으면 True.

    두 값이 모두 알려져 있고(0/1) 서로 다를 때만 비교 불가로 본다. 어느 한쪽이
    None(기준 미상)이면 불일치를 확인할 수 없으므로 비교 가능으로 둔다.
    """
    if previous is None:
        return False
    if latest.is_consolidated is None or previous.is_consolidated is None:
        return True
    return latest.is_consolidated == previous.is_consolidated


def _valuation_metrics(valuation: FinancialMetric | None) -> dict[str, float | None]:
    """최신 월 밸류에이션 행에서 PER/PBR을 그대로 쓰고 EPS/BPS를 역산한다."""
    if valuation is None:
        return {"per": None, "pbr": None, "eps": None, "bps": None}
    return {
        "per": valuation.per,
        "pbr": valuation.pbr,
        "eps": _price_over_multiple(valuation.close_price, valuation.per),
        "bps": _price_over_multiple(valuation.close_price, valuation.pbr),
    }


def _price_over_multiple(close_price: float | None, multiple: float | None) -> float | None:
    """종가 / 배수 (EPS = 종가/PER, BPS = 종가/PBR).

    종가나 배수가 없거나 배수가 0이면 None을 반환한다. 음수 PER(적자)은
    음수 EPS로 그대로 계산한다.
    """
    if close_price is None or multiple is None or multiple == 0:
        return None
    return close_price / multiple
