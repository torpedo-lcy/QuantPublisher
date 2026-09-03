"""quantpublisher.analysis 패키지.

저장된 재무/시장 데이터를 이용한 기본 투자 지표 계산 함수를 제공한다.
크롤링, Git push, Hugo 실행은 이 패키지의 책임이 아니다.
"""

from quantpublisher.analysis.metrics import (
    calculate_bps,
    calculate_debt_ratio,
    calculate_dividend_yield,
    calculate_eps,
    calculate_net_margin,
    calculate_operating_margin,
    calculate_pbr,
    calculate_per,
    calculate_revenue_growth_rate,
    calculate_roa,
    calculate_roe,
)

__all__ = [
    "calculate_bps",
    "calculate_debt_ratio",
    "calculate_dividend_yield",
    "calculate_eps",
    "calculate_net_margin",
    "calculate_operating_margin",
    "calculate_pbr",
    "calculate_per",
    "calculate_revenue_growth_rate",
    "calculate_roa",
    "calculate_roe",
]
