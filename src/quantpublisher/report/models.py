"""리포트 생성에 사용할 데이터 모델.

분석 결과를 웹 리포트(Markdown/Hugo)에서 사용할 구조로 정리한다.
이 모듈은 지표를 계산하지 않는다. 이미 계산된 값을 구조화하는
역할만 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StockMetrics:
    """리포트에 표시할 지표 값 모음.

    각 필드는 quantpublisher.analysis.metrics의 계산 함수 결과를
    그대로 담는다. 계산할 수 없었던 지표는 None으로 표현하며,
    표현 계층(Markdown/Hugo)은 None을 "N/A" 등으로 처리한다.
    """

    roe: float | None = None
    roa: float | None = None
    eps: float | None = None
    bps: float | None = None
    per: float | None = None
    pbr: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    debt_ratio: float | None = None
    dividend_yield: float | None = None
    revenue_growth_rate: float | None = None


@dataclass(frozen=True, slots=True)
class MetricsBasis:
    """지표 값의 기준 시점과 재무제표 기준(연결/별도) (Task 015).

    값만 보여주고 기준 시점을 숨기지 않기 위해 StockMetrics와 함께 리포트에
    전달한다. 기준 데이터가 없으면 해당 필드는 None이다.

    Attributes:
        statement_year: 재무제표 지표(ROE, ROA, 마진, 부채비율, 매출성장률)의
            기준 사업연도 (연간).
        is_consolidated: 1=연결, 0=별도, 모르면 None.
        valuation_month: 밸류에이션 지표(PER, PBR, EPS, BPS)의 기준 월 (YYYY-MM).
    """

    statement_year: int | None = None
    is_consolidated: int | None = None
    valuation_month: str | None = None


@dataclass(frozen=True, slots=True)
class StockReport:
    """종목 하나에 대한 리포트 모델.

    Markdown/Hugo 등 표현 계층은 이 구조체만 참조하면 되고, DB나
    지표 계산 로직에 직접 접근하지 않는다.

    Attributes:
        stock_code: 종목코드.
        name: 종목명.
        market: 시장 구분.
        metrics: 계산된 지표 모음.
        generated_at: 리포트 생성 시각 (ISO 8601 문자열).
        basis: 지표의 기준 연도/월과 연결/별도 구분. 지정하지 않으면 모두 None.
    """

    stock_code: str
    name: str
    market: str
    metrics: StockMetrics
    generated_at: str
    basis: MetricsBasis = MetricsBasis()
