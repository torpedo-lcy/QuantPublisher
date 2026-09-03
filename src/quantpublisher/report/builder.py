"""Security와 계산된 지표를 결합해 StockReport를 생성한다.

이 모듈은 지표를 직접 계산하지 않는다. 계산은
quantpublisher.analysis.metrics에서 이미 끝난 값을 StockMetrics로
전달받는다. DB 접근이나 Markdown/Hugo 관련 로직도 포함하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from quantpublisher.database.models import Security
from quantpublisher.report.models import StockMetrics, StockReport


def build_stock_report(
    security: Security,
    metrics: StockMetrics,
    generated_at: str | None = None,
) -> StockReport:
    """Security와 StockMetrics로부터 StockReport를 생성한다.

    Args:
        security: 종목 정보.
        metrics: 이미 계산된 지표 값 모음.
        generated_at: 리포트 생성 시각 (ISO 8601 문자열). 지정하지
            않으면 UTC 기준 현재 시각을 사용한다.
    """
    timestamp = generated_at if generated_at is not None else _now_iso()
    return StockReport(
        stock_code=security.stock_code,
        name=security.name,
        market=security.market,
        metrics=metrics,
        generated_at=timestamp,
    )


def _now_iso() -> str:
    """UTC 기준 현재 시각을 ISO 8601 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()
