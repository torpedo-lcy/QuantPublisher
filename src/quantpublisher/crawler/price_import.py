"""quant.db 스냅샷의 수정주가(v_adj_price) 읽기/검증과 prices_daily 저장.

단계 분리 (krx_listing.py와 같은 방식):
    read_price_rows   : 스냅샷에서 종목별 수정주가 행을 스트리밍 (읽기 전용)
    parse_price_rows  : 행 검증/변환 (순수 함수, fixture로 테스트 가능)
    save_prices       : PriceRepository를 통한 배치 upsert

prices_daily는 수정주가다 (이전 원천과 같은 기준). 원천 daily_price는 원주가이므로
v_adj_price의 adj_open/adj_high/adj_low/adj_close를 쓰고, 거래량은 adj_factor로 나눠
같은 기준으로 맞춘다. v_adj_price는 corp_event의 REV_SPLIT/BONUS/CAP_DECREASE만 보정한다.

원천 한 행: ``(code, date, open, high, low, close, volume)``. date는 정수 YYYYMMDD이고
prices_daily에는 ``YYYY-MM-DD`` 문자열로 저장한다. 종목별로 date 오름차순으로 읽으므로,
도중에 중단돼도 저장된 MAX(trade_date)부터 증분 수집이 이어진다.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from quantpublisher.database.models import PriceDaily
from quantpublisher.database.price_repository import PriceRepository
from quantpublisher.database.stock_code import STOCK_CODE_PATTERN

logger = logging.getLogger(__name__)

_FIELD_COUNT = 7
_BATCH_SIZE = 50_000
_FETCH_SIZE = 10_000
# 저장된 수정주가와 원천 수정주가가 같은지 볼 때의 상대 허용 오차 (부동소수 반올림 흡수)
_ADJUSTED_CLOSE_REL_TOLERANCE = 1e-9

# 수정주가는 exp(sum(ln(ratio)))라 부동소수 오차가 생긴다 (500 -> 499.9999999999999).
# 소수 4자리로 반올림해 같은 값이 실행마다 같게 저장되도록 한다.
_ADJUSTED_DECIMALS = 4

_ADJUSTED_PRICE_QUERY = (
    f"SELECT code, date, ROUND(adj_open, {_ADJUSTED_DECIMALS}), "
    f"ROUND(adj_high, {_ADJUSTED_DECIMALS}), ROUND(adj_low, {_ADJUSTED_DECIMALS}), "
    f"ROUND(adj_close, {_ADJUSTED_DECIMALS}), ROUND(volume / adj_factor, {_ADJUSTED_DECIMALS}) "
    "FROM v_adj_price WHERE code = ? AND date > ? ORDER BY date"
)


class PriceDataReadError(Exception):
    """quant.db의 daily_price를 읽을 수 없을 때의 오류."""


@dataclass(slots=True)
class PriceParseStats:
    """파싱 중 집계되는 건수 (parse_price_rows가 채운다)."""

    received: int = 0
    valid: int = 0
    skipped_unknown_code: int = 0
    skipped_invalid: int = 0
    unknown_codes: set[str] = field(default_factory=set)


def read_source_first_dates(quant_db_path: Path) -> dict[str, str]:
    """daily_price에 일봉이 있는 종목코드 -> 원천의 첫 거래일(YYYY-MM-DD) (읽기 전용).

    Raises:
        PriceDataReadError: 파일이 없거나 테이블을 읽을 수 없는 경우.
    """
    if not quant_db_path.exists():
        raise PriceDataReadError(f"quant.db 파일이 없습니다: {quant_db_path}")
    try:
        connection = sqlite3.connect(f"file:{quant_db_path}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT code, MIN(date) FROM daily_price GROUP BY code"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise PriceDataReadError(f"daily_price 읽기 실패: {exc}") from exc
    first_dates: dict[str, str] = {}
    for code, first_date in rows:
        iso_date = _to_iso_date(first_date)
        if code is not None and iso_date is not None:
            first_dates[str(code)] = iso_date
    return first_dates


def read_price_rows(
    quant_db_path: Path, since_by_code: Mapping[str, str | None]
) -> Iterator[tuple[Any, ...]]:
    """종목별 수정주가(v_adj_price) 행을 date 오름차순으로 스트리밍한다 (읽기 전용).

    Args:
        quant_db_path: 로컬로 복사한 quant.db 스냅샷.
        since_by_code: 종목코드 -> 이 날짜(YYYY-MM-DD) '이후'만 읽을 기준일.
            None이면 해당 종목은 전체를 읽는다 (최초 백필/전체 덮어쓰기).

    Raises:
        PriceDataReadError: 테이블을 읽을 수 없거나 기준일 형식이 틀린 경우.
    """
    try:
        connection = sqlite3.connect(f"file:{quant_db_path}?mode=ro", uri=True)
        try:
            for code in sorted(since_by_code):
                since = since_by_code[code]
                cursor = connection.execute(_ADJUSTED_PRICE_QUERY, (code, _since_to_int(since)))
                while chunk := cursor.fetchmany(_FETCH_SIZE):
                    yield from chunk
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise PriceDataReadError(f"v_adj_price 읽기 실패: {exc}") from exc


def find_readjusted_codes(
    quant_db_path: Path, stored_closes: Mapping[str, tuple[str, float]]
) -> set[str]:
    """저장된 수정종가가 원천 수정종가와 달라진 종목코드를 찾는다 (읽기 전용).

    분할/병합/감자 이벤트가 새로 생기면 그 이전 날짜의 수정주가가 모두 바뀐다. 이벤트
    날짜와 기록 시점이 다를 수 있으므로, 이벤트를 보지 않고 원천의 첫 거래일 종가를
    저장된 값과 비교한다. 달라졌으면 그 종목의 과거 가격 전체를 다시 가져와야 한다.

    Args:
        stored_closes: 종목코드 -> (원천 첫 거래일 YYYY-MM-DD, 그날 저장된 close).
            저장된 행이 없는 종목은 넣지 않는다.
    """
    readjusted: set[str] = set()
    try:
        connection = sqlite3.connect(f"file:{quant_db_path}?mode=ro", uri=True)
        try:
            for code in sorted(stored_closes):
                trade_date, stored_close = stored_closes[code]
                row = connection.execute(
                    f"SELECT ROUND(adj_close, {_ADJUSTED_DECIMALS}) FROM v_adj_price "
                    "WHERE code = ? AND date = ?",
                    (code, _since_to_int(trade_date)),
                ).fetchone()
                if row is None or row[0] is None:
                    continue
                if not math.isclose(
                    float(row[0]), stored_close, rel_tol=_ADJUSTED_CLOSE_REL_TOLERANCE
                ):
                    readjusted.add(code)
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise PriceDataReadError(f"v_adj_price 읽기 실패: {exc}") from exc
    return readjusted


def parse_price_rows(
    rows: Iterable[tuple[Any, ...]],
    known_codes: set[str],
    stats: PriceParseStats,
) -> Iterator[PriceDaily]:
    """수정주가 행을 검증해 PriceDaily로 변환한다.

    다음 행은 건너뛰고 stats에 센다 (조용히 버리지 않는다):
        - 필드 수가 7개가 아님 / 종목코드가 숫자/영문 대문자 6자리가 아님 -> invalid
        - securities(known_codes)에 없는 종목코드 -> unknown_code (종목별 1회 경고 로그)
        - date가 실제로 존재하는 정수 YYYYMMDD가 아님 -> invalid
        - 가격/거래량이 비어 있거나 숫자가 아님(NaN/inf 포함) -> invalid
        - 가격/거래량이 음수 -> invalid
    0은 허용한다 (거래정지일에 시가/고가/저가가 0으로 기록되는 경우가 있다).
    """
    for row in rows:
        stats.received += 1
        if len(row) != _FIELD_COUNT:
            stats.skipped_invalid += 1
            continue
        raw_code, raw_date, *raw_numbers = row
        stock_code = str(raw_code).strip() if raw_code is not None else ""

        if not STOCK_CODE_PATTERN.match(stock_code):
            stats.skipped_invalid += 1
            continue
        if stock_code not in known_codes:
            stats.skipped_unknown_code += 1
            if stock_code not in stats.unknown_codes:
                stats.unknown_codes.add(stock_code)
                logger.warning("price_unknown_stock_code skipped stock_code=%s", stock_code)
            continue
        trade_date = _to_iso_date(raw_date)
        if trade_date is None:
            stats.skipped_invalid += 1
            continue
        values = [_parse_non_negative_number(value) for value in raw_numbers]
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


def _since_to_int(since: str | None) -> int:
    """YYYY-MM-DD 기준일을 daily_price.date 비교용 정수로 바꾼다. None이면 0(전체)."""
    if since is None:
        return 0
    try:
        return int(datetime.strptime(since, "%Y-%m-%d").strftime("%Y%m%d"))
    except ValueError as exc:
        raise PriceDataReadError(f"잘못된 기준일 형식 (YYYY-MM-DD 필요): {since!r}") from exc


def _to_iso_date(value: Any) -> str | None:
    """정수 YYYYMMDD를 YYYY-MM-DD로 바꾼다. 형식이 틀리거나 없는 날짜면 None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    try:
        return datetime.strptime(str(value), "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_non_negative_number(value: Any) -> float | None:
    """숫자를 float로 변환한다. 비었거나 숫자가 아니거나 음수/NaN/inf면 None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number
