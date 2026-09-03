"""KRX 상장 종목 목록 수집기.

FinanceDataReader를 이용해 KRX(코스피/코스닥/코넥스) 상장 종목 목록을
수집하고, 검증을 거쳐 Security 레코드로 변환한 뒤 저장한다.

단계 분리:
    fetch_krx_listing  : 외부 라이브러리 호출 (네트워크)
    parse_krx_listing  : 원시 데이터 검증/변환 (순수 함수, fixture로 테스트 가능)
    save_krx_listing   : SecurityRepository를 통한 DB 저장
    collect_krx_listing: 위 세 단계를 순서대로 실행하는 진입점

크롤러는 데이터 수집과 검증만 담당한다.
HTML 생성, 투자 판단, 배포는 이 모듈의 책임이 아니다.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any, Iterable, Mapping

from quantpublisher.database.models import Security
from quantpublisher.database.security_repository import SecurityRepository

logger = logging.getLogger(__name__)

_STOCK_CODE_PATTERN = re.compile(r"^\d{6}$")
_VALID_MARKETS = {"KOSPI", "KOSDAQ", "KONEX"}


class KrxListingFetchError(Exception):
    """KRX 종목 목록 수집(외부 호출) 중 발생한 오류."""


def fetch_krx_listing() -> list[dict[str, Any]]:
    """FinanceDataReader를 통해 KRX 종목 목록 원시 데이터를 가져온다.

    네트워크/외부 라이브러리 호출을 이 함수에 격리하여, 파싱과 저장
    로직은 네트워크 없이 테스트할 수 있도록 한다.

    Raises:
        KrxListingFetchError: 라이브러리가 없거나 수집에 실패한 경우.
    """
    try:
        import FinanceDataReader as fdr
    except ImportError as exc:
        raise KrxListingFetchError(
            "FinanceDataReader가 설치되어 있지 않습니다. "
            "'uv add financedatareader'로 추가하세요."
        ) from exc

    try:
        df = fdr.StockListing("KRX")
    except Exception as exc:  # 외부 라이브러리/네트워크 오류는 예측 불가하므로 포괄 처리 후 전달
        raise KrxListingFetchError(f"KRX 종목 목록 수집 실패: {exc}") from exc

    return df.to_dict(orient="records")


def parse_krx_listing(raw_rows: Iterable[Mapping[str, Any]]) -> list[Security]:
    """원시 종목 목록 데이터를 검증하여 Security 목록으로 변환한다.

    다음 행은 건너뛴다:
        - 종목코드 또는 종목명이 비어 있는 행
        - 종목코드가 6자리 숫자가 아닌 행
        - 시장 구분이 KOSPI/KOSDAQ/KONEX가 아닌 행

    동일한 종목코드가 여러 번 나타나면 마지막 행의 값으로 덮어쓴다
    (수집 결과 자체의 중복 저장을 방지).
    """
    rows = list(raw_rows)
    securities: dict[str, Security] = {}
    skipped = 0

    for row in rows:
        stock_code = _normalize_stock_code(row.get("Code"))
        name = _normalize_name(row.get("Name"))
        market = _normalize_market(row.get("Market"))

        if stock_code is None or name is None or market is None:
            skipped += 1
            continue

        securities[stock_code] = Security(stock_code=stock_code, name=name, market=market)

    logger.info(
        "krx_listing_parsed total=%d valid=%d skipped=%d",
        len(rows),
        len(securities),
        skipped,
    )
    return list(securities.values())


def save_krx_listing(connection: sqlite3.Connection, securities: Iterable[Security]) -> int:
    """Security 목록을 securities 테이블에 upsert한다.

    Returns:
        upsert된 건수.
    """
    repository = SecurityRepository(connection)
    count = 0
    for security in securities:
        repository.upsert(security)
        count += 1
    logger.info("krx_listing_saved count=%d", count)
    return count


def collect_krx_listing(connection: sqlite3.Connection) -> int:
    """KRX 종목 목록을 수집, 검증하고 DB에 저장한다.

    fetch -> parse -> save 순서로 실행한다. 각 단계에서 발생한 예외는
    조용히 무시하지 않고 그대로 상위로 전달한다.

    Returns:
        DB에 upsert된 종목 수.
    """
    raw_rows = fetch_krx_listing()
    securities = parse_krx_listing(raw_rows)
    return save_krx_listing(connection, securities)


def _normalize_stock_code(value: Any) -> str | None:
    """값을 6자리 종목코드 문자열로 정규화한다. 유효하지 않으면 None."""
    if value is None:
        return None
    code = str(value).strip()
    if not _STOCK_CODE_PATTERN.match(code):
        return None
    return code


def _normalize_name(value: Any) -> str | None:
    """값을 종목명 문자열로 정규화한다. 비어 있으면 None."""
    if value is None:
        return None
    name = str(value).strip()
    return name or None


def _normalize_market(value: Any) -> str | None:
    """값을 시장 구분 문자열로 정규화한다. 유효하지 않으면 None."""
    if value is None:
        return None
    market = str(value).strip().upper()
    return market if market in _VALID_MARKETS else None
