"""가격 차트용 JSON 데이터를 만든다 (Task 017).

일봉(PriceDaily)을 브라우저의 정적 JS 차트가 읽는 compact JSON으로 바꾸고
website/static/charts/prices/<종목코드>.json으로 저장한다. 이동평균 같은
계산은 JS 쪽에서 하며, 이 모듈은 데이터를 계산하지 않고 형식만 바꾼다.

`.gitignore`의 `data/` 패턴이 website/static/data/까지 무시하므로 디렉터리
이름은 `charts`로 둔다.

가격 JSON 형식 (열 방향 배열, 길이가 모두 같다):
    {"code": "005930", "t": [일 단위 epoch...], "c": [종가...], "v": [거래량...]}
t는 1970-01-01부터의 일수다 (JS에서 86400을 곱해 초 단위로 쓴다).

재무 JSON (website/static/charts/financials/<종목코드>.json, Task 018):
    {"code": "005930", "y": [연도...], "s": [매출액...], "o": [영업이익...], "n": [순이익...]}
금액은 억원 단위 정수이고 값이 없으면 null이다.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Sequence

from quantpublisher.database.models import PriceDaily
from quantpublisher.report.models import FinancialYear

logger = logging.getLogger(__name__)

# 차트에 담는 최근 거래일 수 (약 1.5년). 이동평균(최대 120일)을 첫 화면부터
# 그릴 수 있도록 표시 구간(약 250일)보다 길게 둔다. 값을 키우면 종목당 JSON
# 크기와 가져오기 때마다의 git 변경량이 같이 늘어난다.
CHART_MAX_ROWS = 370

# 재무 차트는 점이 한 개면 추이가 아니므로 이 연수 이상일 때만 만든다.
FINANCIAL_CHART_MIN_YEARS = 2

_EPOCH = date(1970, 1, 1)
_WON_PER_EOK = 100_000_000  # 1억원


def build_price_chart_data(
    stock_code: str, prices: Sequence[PriceDaily]
) -> dict[str, object] | None:
    """일봉으로 차트 데이터를 만든다. 종가가 있는 행이 없으면 None.

    입력은 거래일 오름차순이어야 한다. 종가가 없는 행은 건너뛰고, 거래량이
    없으면 0으로 둔다. 정수로 떨어지는 값은 int로 바꿔 JSON 크기를 줄인다.
    """
    days: list[int] = []
    closes: list[float | int] = []
    volumes: list[float | int] = []
    for price in prices:
        if price.close is None:
            continue
        days.append((date.fromisoformat(price.trade_date) - _EPOCH).days)
        closes.append(_compact_number(price.close))
        volumes.append(_compact_number(price.volume if price.volume is not None else 0))
    if not days:
        return None
    return {"code": stock_code, "t": days, "c": closes, "v": volumes}


def render_chart_json(data: dict[str, object]) -> str:
    """차트 데이터를 결정적인 compact JSON 문자열로 만든다."""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n"


def write_price_chart_json(
    stock_code: str, prices: Sequence[PriceDaily], output_dir: Path
) -> Path | None:
    """가격 차트 JSON을 저장한다. 데이터가 없으면 파일을 만들지 않고 None을 반환한다.

    기존 파일과 내용이 같으면 다시 쓰지 않는다 (write_stock_report_markdown과 같은 이유).
    """
    return _write_chart_json(stock_code, build_price_chart_data(stock_code, prices), output_dir)


def build_financial_chart_data(
    stock_code: str, history: Sequence[FinancialYear]
) -> dict[str, object] | None:
    """재무 시계열로 차트 데이터를 만든다. 연도가 FINANCIAL_CHART_MIN_YEARS 미만이면 None."""
    if len(history) < FINANCIAL_CHART_MIN_YEARS:
        return None
    return {
        "code": stock_code,
        "y": [item.year for item in history],
        "s": [_to_eok(item.sales) for item in history],
        "o": [_to_eok(item.operating_income) for item in history],
        "n": [_to_eok(item.net_income) for item in history],
    }


def write_financial_chart_json(
    stock_code: str, history: Sequence[FinancialYear], output_dir: Path
) -> Path | None:
    """재무 차트 JSON을 저장한다. 데이터가 부족하면 만들지 않고 None을 반환한다."""
    return _write_chart_json(stock_code, build_financial_chart_data(stock_code, history), output_dir)


def _write_chart_json(
    stock_code: str, data: dict[str, object] | None, output_dir: Path
) -> Path | None:
    if data is None:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    content = render_chart_json(data)
    file_path = output_dir / f"{stock_code}.json"
    if file_path.exists() and file_path.read_text(encoding="utf-8") == content:
        return file_path
    file_path.write_text(content, encoding="utf-8")
    logger.info("Chart JSON written: stock_code=%s path=%s", stock_code, file_path)
    return file_path


def _to_eok(value: float | None) -> int | None:
    """원 단위 금액을 억원 단위 정수로 바꾼다. 없으면 None."""
    return None if value is None else round(value / _WON_PER_EOK)


def _compact_number(value: float) -> float | int:
    """12000.0 같은 정수형 실수는 int로 바꾼다."""
    as_float = float(value)
    return int(as_float) if as_float.is_integer() else as_float
