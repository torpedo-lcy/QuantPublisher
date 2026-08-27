"""securities 테이블에 대한 데이터 접근을 담당한다.

SQL은 이 모듈에 모으고, 분석 의미나 계산 로직은 포함하지 않는다.
"""

from __future__ import annotations

import logging
import sqlite3

from quantpublisher.database.models import Security

logger = logging.getLogger(__name__)


class SecurityRepository:
    """securities 테이블에 대한 CRUD를 제공하는 Repository.

    호출자가 sqlite3.Connection의 생성과 종료를 책임진다.
    이 클래스는 connection을 열거나 닫지 않는다.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(self, security: Security) -> None:
        """종목을 등록하거나, 이미 존재하면 정보를 갱신한다.

        stock_code를 기준으로 중복을 방지한다 (idempotent).
        """
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO securities (stock_code, name, market, is_active, updated_at)
                VALUES (:stock_code, :name, :market, :is_active, datetime('now'))
                ON CONFLICT(stock_code) DO UPDATE SET
                    name = excluded.name,
                    market = excluded.market,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """,
                {
                    "stock_code": security.stock_code,
                    "name": security.name,
                    "market": security.market,
                    "is_active": int(security.is_active),
                },
            )
        logger.info(
            "security_upserted stock_code=%s market=%s",
            security.stock_code,
            security.market,
        )

    def get_by_code(self, stock_code: str) -> Security | None:
        """종목코드로 종목을 조회한다. 없으면 None을 반환한다."""
        row = self._connection.execute(
            "SELECT * FROM securities WHERE stock_code = ?",
            (stock_code,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_security(row)

    def list_all(self, active_only: bool = False) -> list[Security]:
        """등록된 모든 종목을 조회한다.

        active_only가 True이면 현재 거래 가능한 종목만 반환한다.
        """
        if active_only:
            rows = self._connection.execute(
                "SELECT * FROM securities WHERE is_active = 1 ORDER BY stock_code"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM securities ORDER BY stock_code"
            ).fetchall()
        return [_row_to_security(row) for row in rows]

    def delete(self, stock_code: str) -> bool:
        """종목을 삭제한다. 삭제된 행이 있으면 True, 없으면 False를 반환한다."""
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM securities WHERE stock_code = ?",
                (stock_code,),
            )
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("security_deleted stock_code=%s", stock_code)
        return deleted


def _row_to_security(row: sqlite3.Row) -> Security:
    return Security(
        stock_code=row["stock_code"],
        name=row["name"],
        market=row["market"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
