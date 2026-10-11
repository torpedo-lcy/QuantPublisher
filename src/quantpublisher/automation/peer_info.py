"""전 종목 지표를 동종 비교 입력으로 바꾸고, 비교 결과를 리포트용으로 바꾼다 (Task 020).

DB에 접근하지 않는 순수 함수만 둔다. 비교 계산 자체는 analysis.peer_comparison이 한다.
"""

from __future__ import annotations

from typing import Mapping

from quantpublisher.analysis.ksic import industry_name
from quantpublisher.analysis.peer_comparison import (
    GroupComparison,
    PeerComparison,
    PeerInput,
)
from quantpublisher.database.models import CompanyProfile, Security
from quantpublisher.report import MetricsBasis, PeerGroup, PeerMetricRow, StockMetrics

_LABELS = {
    "per": "PER",
    "pbr": "PBR",
    "roe": "ROE (%)",
    "operating_margin": "영업이익률 (%)",
}


def build_peer_inputs(
    securities: list[Security],
    loaded: Mapping[str, tuple[StockMetrics, MetricsBasis]],
    profiles: Mapping[str, CompanyProfile],
) -> list[PeerInput]:
    """종목별 지표와 기준 시점, 업종코드로 비교 입력을 만든다.

    PER, PBR은 밸류에이션 기준 월, ROE, 영업이익률은 재무제표 기준 연도가
    같은 종목끼리만 비교되도록 기준 시점을 함께 넘긴다.
    """
    inputs = []
    for security in securities:
        metrics, basis = loaded[security.stock_code]
        profile = profiles.get(security.stock_code)
        year = str(basis.statement_year) if basis.statement_year is not None else None
        inputs.append(
            PeerInput(
                stock_code=security.stock_code,
                market=security.market,
                industry_code=profile.induty_code if profile is not None else None,
                values={
                    "per": metrics.per,
                    "pbr": metrics.pbr,
                    "roe": metrics.roe,
                    "operating_margin": metrics.operating_margin,
                },
                bases={
                    "per": basis.valuation_month,
                    "pbr": basis.valuation_month,
                    "roe": year,
                    "operating_margin": year,
                },
            )
        )
    return inputs


def build_peer_groups(
    comparison: PeerComparison | None,
) -> tuple[PeerGroup | None, PeerGroup | None]:
    """비교 결과를 (업종, 시장) 리포트용 그룹으로 바꾼다.

    이 종목의 비교 지표 값이 하나도 없으면 보여줄 내용이 없으므로 (None, None)이다.
    """
    if comparison is None or comparison.market is None:
        return None, None
    if all(metric.value is None for metric in comparison.market.metrics):
        return None, None
    industry = _to_group(comparison.industry, _industry_description) if comparison.industry else None
    return industry, _to_group(comparison.market, lambda group: group.key)


def _industry_description(group: GroupComparison) -> str:
    """업종 그룹 설명. 이름은 2자리 중분류의 것이므로 3자리 소분류는 '중 KSIC xxx 동종'으로 쓴다."""
    name = industry_name(group.key)
    if name is None:
        return f"KSIC {group.key}"
    if len(group.key) >= 3:
        return f"{name} 중 KSIC {group.key} 동종"
    return f"{name} (KSIC {group.key})"


def _to_group(group: GroupComparison, describe) -> PeerGroup:
    return PeerGroup(
        description=describe(group),
        size=group.size,
        rows=tuple(
            PeerMetricRow(
                key=metric.key,
                label=_LABELS[metric.key],
                value=metric.value,
                median=metric.median,
                rank=metric.rank,
                sample=metric.sample,
            )
            for metric in group.metrics
        ),
    )
