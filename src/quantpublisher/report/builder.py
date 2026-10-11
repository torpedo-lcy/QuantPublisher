"""Security와 계산된 지표를 결합해 StockReport를 생성한다.

이 모듈은 지표를 직접 계산하지 않는다. 계산은
quantpublisher.analysis.metrics에서 이미 끝난 값을 StockMetrics로
전달받는다. DB 접근이나 Markdown/Hugo 관련 로직도 포함하지 않는다.
"""

from __future__ import annotations

from quantpublisher.database.models import Security
from quantpublisher.report.models import MetricsBasis, StockMetrics, StockReport


def build_stock_report(
    security: Security,
    metrics: StockMetrics,
    data_date: str | None = None,
    basis: MetricsBasis | None = None,
) -> StockReport:
    """Security와 StockMetrics로부터 StockReport를 생성한다.

    Args:
        security: 종목 정보.
        metrics: 이미 계산된 지표 값 모음.
        data_date: 데이터 기준일 (YYYY-MM-DD). 실행 시각을 쓰지 않는 이유는
            데이터가 그대로인 종목의 파일이 매일 바뀌지 않게 하기 위해서다.
            지정하지 않으면 None이며 페이지에는 "N/A"로 표시된다.
        basis: 지표의 기준 연도/월과 연결/별도 구분. 지정하지 않으면
            기준 정보가 없는 MetricsBasis()를 사용한다.
    """
    return StockReport(
        stock_code=security.stock_code,
        name=security.name,
        market=security.market,
        metrics=metrics,
        data_date=data_date,
        basis=basis if basis is not None else MetricsBasis(),
    )
