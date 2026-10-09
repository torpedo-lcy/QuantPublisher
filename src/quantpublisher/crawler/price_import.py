"""외부 일봉 PSV 파싱/검증과 prices_daily 저장.

단계 분리 (krx_listing.py와 같은 방식):
    parse_price_lines : PSV 줄 검증/변환 (순수 함수, fixture로 테스트 가능)
    save_prices       : PriceRepository를 통한 배치 upsert

PSV 한 줄: ``종목코드|Time|open|high|low|close|volume``
원본은 종목별로 Time 오름차순이므로, 도중에 중단돼도 저장된 MAX(trade_date)부터
증분 수집이 이어진다.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from itertools import islice
from typing import Iterable, Iterator

from quantpublisher.database.models import PriceDaily
from quantpublisher.database.price_repository import PriceRepository
from quantpublisher.database.stock_code import STOCK_CODE_PATTERN

logger = logging.getLogger(__name__)

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FIELD_COUNT = 7
_BATCH_SIZE = 50_000


@dataclass(slots=True)
class PriceParseStats:
    """파싱 중 집계되는 건수 (parse_price_lines가 채운다)."""

    received: int = 0
    valid: int = 0
    skipped_unknown_code: int = 0
    skipped_invalid: int = 0
    unknown_codes: set[str] = field(default_factory=set)


def parse_price_lines(
    lines: Iterable[str],
    known_codes: set[str],
    stats: PriceParseStats,
) -> Iterator[PriceDaily]:
    """PSV 줄을 검증해 PriceDaily로 변환한다.

    다음 줄은 건너뛰고 stats에 센다 (조용히 버리지 않는다):
        - 필드 수가 7개가 아님 / 종목코드가 6자리 숫자가 아님 -> invalid
        - securities(known_codes)에 없는 종목코드 -> unknown_code (종목별 1회 경고 로그)
        - trade_date가 실제로 존재하는 YYYY-MM-DD가 아님 -> invalid
        - 가격/거래량이 비어 있거나 숫자가 아님(NaN/inf 포함) -> invalid
        - 가격/거래량이 음수 -> invalid
    0은 허용한다 (거래정지일에 시가/고가/저가가 0으로 기록되는 경우가 있다).
    """
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        stats.received += 1
        parts = line.split("|")
        if len(parts) != _FIELD_COUNT:
            stats.skipped_invalid += 1
            continue
        stock_code, trade_date, *numbers = (part.strip() for part in parts)

        if not STOCK_CODE_PATTERN.match(stock_code):
            stats.skipped_invalid += 1
            continue
        if stock_code not in known_codes:
            stats.skipped_unknown_code += 1
            if stock_code not in stats.unknown_codes:
                stats.unknown_codes.add(stock_code)
                logger.warning("price_unknown_stock_code skipped stock_code=%s", stock_code)
            continue
        if not _is_valid_date(trade_date):
            stats.skipped_invalid += 1
            continue
        values = [_parse_non_negative_number(text) for text in numbers]
        if any(value is None for value in values):
            stats.skipped_invalid += 1
            continue

        open_, high, low, close, volume = values
        stats.valid += 1
        yield PriceDaily(
            stock_code=stock_code,
            trade_date=trade_date,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )


def save_prices(connection: sqlite3.Connection, prices: Iterable[PriceDaily]) -> int:
    """일봉을 배치 단위로 upsert한다. 배치마다 하나의 트랜잭션이다.

    Returns:
        upsert한 행 수 (신규 + 갱신).
    """
    repository = PriceRepository(connection)
    iterator = iter(prices)
    total = 0
    while batch := list(islice(iterator, _BATCH_SIZE)):
        total += repository.upsert_many(batch)
    logger.info("prices_saved count=%d", total)
    return total


def _is_valid_date(text: str) -> bool:
    if not _DATE_PATTERN.match(text):
        return False
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _parse_non_negative_number(text: str) -> float | None:
    """숫자 문자열을 float로 변환한다. 비었거나 숫자가 아니거나 음수/NaN/inf면 None."""
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number
