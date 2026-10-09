"""quant.db의 stock_master에서 DART 고유번호(corp_code)를 읽어 securities에 채운다.

quant.db는 항상 읽기 전용으로 연다. 이 모듈이 받는 quant.db는 외부 Mac에서
``.backup``으로 만든 스냅샷을 로컬로 복사한 파일이다.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quantpublisher.database.security_repository import SecurityRepository
from quantpublisher.database.stock_code import STOCK_CODE_PATTERN

logger = logging.getLogger(__name__)

_CORP_CODE_DIGITS = re.compile(r"^\d{1,8}$")
_CORP_CODE_LENGTH = 8


class StockMasterReadError(Exception):
    """quant.db의 stock_master를 읽을 수 없을 때의 오류."""


@dataclass(frozen=True, slots=True)
class CorpCodeImportResult:
    """corp_code 가져오기 결과.

    Attributes:
        master_rows: stock_master에서 읽은 행 수.
        updated: 값이 실제로 바뀐 securities 행 수.
        skipped_unknown_code: securities에 없는 종목코드라 건너뛴 행 수.
        skipped_invalid: 종목코드/corp_code가 비었거나 형식이 틀려 건너뛴 행 수.
    """

    master_rows: int
    updated: int
    skipped_unknown_code: int
    skipped_invalid: int


def read_stock_master(quant_db_path: Path) -> list[tuple[Any, Any]]:
    """stock_master의 (stock_code, corp_code) 원시 값을 읽는다 (읽기 전용).

    Raises:
        StockMasterReadError: 파일이 없거나 테이블/열을 읽을 수 없는 경우.
    """
    if not quant_db_path.exists():
        raise StockMasterReadError(f"quant.db 파일이 없습니다: {quant_db_path}")
    uri = f"file:{quant_db_path}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            return connection.execute("SELECT stock_code, corp_code FROM stock_master").fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise StockMasterReadError(f"stock_master 읽기 실패: {exc}") from exc


def normalize_corp_code(value: Any) -> str | None:
    """corp_code를 DART 고유번호 8자리 문자열로 정규화한다. 유효하지 않으면 None.

    숫자만 허용한다. 8자리보다 짧으면 앞을 0으로 채운다 (DART 고유번호는 항상
    8자리이며, 정수로 저장되면서 앞자리 0이 사라진 경우를 복원하는 규칙이다).
    """
    if value is None:
        return None
    text = str(value).strip()
    if not _CORP_CODE_DIGITS.match(text):
        return None
    return text.zfill(_CORP_CODE_LENGTH)


def import_corp_codes(
    connection: sqlite3.Connection, quant_db_path: Path
) -> CorpCodeImportResult:
    """stock_master의 corp_code를 securities에 반영한다 (idempotent).

    securities에 없는 종목은 건너뛰고(새로 만들지 않는다), corp_code가 비어 있는
    행은 기존 값을 지우지 않도록 건너뛴다. 건너뛴 건수는 결과와 로그에 남는다.
    """
    master_rows = read_stock_master(quant_db_path)
    known_codes = {s.stock_code for s in SecurityRepository(connection).list_all()}

    corp_codes: dict[str, str] = {}
    skipped_unknown = 0
    skipped_invalid = 0
    for raw_code, raw_corp_code in master_rows:
        stock_code = str(raw_code).strip() if raw_code is not None else ""
        corp_code = normalize_corp_code(raw_corp_code)
        if not STOCK_CODE_PATTERN.match(stock_code) or corp_code is None:
            skipped_invalid += 1
            continue
        if stock_code not in known_codes:
            skipped_unknown += 1
            continue
        corp_codes[stock_code] = corp_code

    updated = SecurityRepository(connection).update_corp_codes(corp_codes)
    logger.info(
        "corp_codes_imported master_rows=%d updated=%d skipped_unknown_code=%d skipped_invalid=%d",
        len(master_rows),
        updated,
        skipped_unknown,
        skipped_invalid,
    )
    return CorpCodeImportResult(
        master_rows=len(master_rows),
        updated=updated,
        skipped_unknown_code=skipped_unknown,
        skipped_invalid=skipped_invalid,
    )
