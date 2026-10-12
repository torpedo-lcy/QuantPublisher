"""시장 대표지수(KOSPI, KOSDAQ) 일봉을 받아 가격 차트용 JSON으로 저장한다 (Task 023).

외부 호출(FinanceDataReader)은 fetch_index_closes에 격리해 변환/저장 로직을 네트워크 없이 테스트한다.
지수는 DB에 저장하지 않고 website/static/charts/index/<지수>.json만 만든다. 실패해도 기존 파일은
그대로 두므로 지수선이 오래될 수는 있지만 페이지가 깨지지 않는다.

`uv run python -m quantpublisher.crawler.index_chart`로 단독 실행할 수 있다.
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from config.settings import PROJECT_ROOT
from quantpublisher.report.chart_data import CHART_MAX_ROWS, INDEX_SYMBOLS, write_index_chart_json

logger = logging.getLogger(__name__)

# CHART_MAX_ROWS(거래일)를 채우기 충분한 달력일 수.
_FETCH_CALENDAR_DAYS = int(CHART_MAX_ROWS * 7 / 5) + 60

_DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "website" / "static" / "charts" / "index"


class IndexFetchError(Exception):
    """지수 일봉 수집(외부 호출) 중 발생한 오류."""


def fetch_index_closes(symbol: str, start: date) -> list[tuple[str, float]]:
    """FinanceDataReader로 지수 종가 목록 [(YYYY-MM-DD, 종가)]를 오름차순으로 가져온다.

    종가가 비었거나 NaN, 0 이하인 행은 건너뛴다.

    Raises:
        IndexFetchError: 라이브러리가 없거나 수집에 실패한 경우.
    """
    try:
        import FinanceDataReader as fdr
    except ImportError as exc:
        raise IndexFetchError("FinanceDataReader가 설치되어 있지 않습니다.") from exc
    try:
        frame = fdr.DataReader(symbol, start.isoformat())
    except Exception as exc:  # 외부 라이브러리/네트워크 오류는 예측 불가하므로 포괄 처리 후 전달
        raise IndexFetchError(f"지수 수집 실패 symbol={symbol}: {exc}") from exc

    closes: list[tuple[str, float]] = []
    for day, close in frame["Close"].items():
        value = float(close)
        if math.isnan(value) or value <= 0:
            continue
        closes.append((day.strftime("%Y-%m-%d"), value))
    return closes


def update_index_charts(
    output_dir: Path = _DEFAULT_OUTPUT_DIR,
    fetch: Callable[[str, date], list[tuple[str, float]]] = fetch_index_closes,
    today: date | None = None,
) -> int:
    """모든 대표지수의 차트 JSON을 갱신하고 성공한 개수를 반환한다.

    한 지수가 실패하면 그 지수의 기존 파일을 두고 경고만 남긴 뒤 다음 지수로 넘어간다.
    """
    start = (today or date.today()) - timedelta(days=_FETCH_CALENDAR_DAYS)
    updated = 0
    for market, symbol in INDEX_SYMBOLS.items():
        try:
            closes = fetch(symbol, start)
        except IndexFetchError as exc:
            logger.warning("index_chart_failed market=%s reason=%s", market, exc)
            continue
        if write_index_chart_json(market, closes, output_dir) is None:
            logger.warning("index_chart_empty market=%s", market)
            continue
        updated += 1
    logger.info("index_charts_updated count=%d/%d", updated, len(INDEX_SYMBOLS))
    return updated


def main() -> int:
    """CLI 진입점. 모든 지수가 갱신되면 0, 아니면 1."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return 0 if update_index_charts() == len(INDEX_SYMBOLS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
