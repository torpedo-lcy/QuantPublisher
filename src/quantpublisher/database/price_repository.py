"""prices_daily 테이블에 대한 데이터 접근을 담당한다.

SQL은 이 모듈에 모으고, 분석 의미나 계산 로직은 포함하지 않는다.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Iterable

from quantpublisher.database.models import PriceDaily

logger = logging.getLogger(__name__)


class PriceRepository:
    """prices_daily 테이블 Repository.

    호출자가 sqlite3.Connection의 생성과 종료를 책임진다.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert_many(self, prices: Iterable[PriceDaily]) -> int:
        """일봉을 (stock_code, trade_date) 기준으로 upsert한다.

        한 번의 호출은 하나의 트랜잭션이다. 도중에 실패하면 이 호출의
        변경은 모두 rollback된다.

        Returns:
            처리한 행 수 (신규 + 갱신).
        """
        rows = [
            {
                "stock_code": p.stock_code,
                "trade_date": p.trade_date,
                "open": p.open,
                "high": p.high,
                "low": p.low,
                "close": p.close,
                "volume": p.volume,
            }
            for p in prices
        ]
        if not rows:
            return 0
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO prices_daily
                    (stock_code, trade_date, open, high, low, close, volume, updated_at)
                VALUES
                    (:stock_code, :trade_date, :open, :high, :low, :close, :volume,
                     datetime('now'))
                ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def get_latest_trade_dates(self) -> dict[str, str]:
        """종목별로 저장된 가장 최근 trade_date를 반환한다 (증분 수집 기준)."""
        rows = self._connection.execute(
            "SELECT stock_code, MAX(trade_date) AS latest FROM prices_daily GROUP BY stock_code"
        ).fetchall()
        return {row["stock_code"]: row["latest"] for row in rows}

    def list_by_code(self, stock_code: str) -> list[PriceDaily]:
        """한 종목의 일봉을 거래일 오름차순으로 반환한다."""
        rows = self._connection.execute(
            "SELECT * FROM prices_daily WHERE stock_code = ? ORDER BY trade_date",
            (stock_code,),
        ).fetchall()
        return [
            PriceDaily(
                stock_code=r["stock_code"],
                trade_date=r["trade_date"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
            )
            for r in rows
        ]
