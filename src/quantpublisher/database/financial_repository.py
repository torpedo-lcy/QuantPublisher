"""financial_statements / financial_metrics 테이블에 대한 데이터 접근을 담당한다.

SQL은 이 모듈에 모으고, 분석 의미나 계산 로직은 포함하지 않는다.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Iterable

from quantpublisher.database.models import FinancialMetric, FinancialStatement

logger = logging.getLogger(__name__)


class FinancialRepository:
    """재무제표/밸류에이션 Repository.

    호출자가 sqlite3.Connection의 생성과 종료를 책임진다.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert_statements(self, statements: Iterable[FinancialStatement]) -> int:
        """연간 재무제표를 (stock_code, year, report_type) 기준으로 upsert한다.

        한 번의 호출은 하나의 트랜잭션이다. 도중에 실패하면 이 호출의 변경은
        모두 rollback된다. 새 값이 NULL이면 기존 값도 NULL로 덮어쓴다
        (원천이 "미공시"로 바뀌면 이전의 잘못된 값이 남지 않게 하기 위함).

        Returns:
            처리한 행 수 (신규 + 갱신).
        """
        rows = [
            {
                "stock_code": s.stock_code,
                "year": s.year,
                "report_type": s.report_type,
                "assets": s.assets,
                "liabilities": s.liabilities,
                "equity": s.equity,
                "current_assets": s.current_assets,
                "current_liab": s.current_liab,
                "sales": s.sales,
                "gross_profit": s.gross_profit,
                "operating_income": s.operating_income,
                "net_income": s.net_income,
                "is_consolidated": s.is_consolidated,
            }
            for s in statements
        ]
        if not rows:
            return 0
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO financial_statements
                    (stock_code, year, report_type, assets, liabilities, equity,
                     current_assets, current_liab, sales, gross_profit,
                     operating_income, net_income, is_consolidated, updated_at)
                VALUES
                    (:stock_code, :year, :report_type, :assets, :liabilities, :equity,
                     :current_assets, :current_liab, :sales, :gross_profit,
                     :operating_income, :net_income, :is_consolidated, datetime('now'))
                ON CONFLICT(stock_code, year, report_type) DO UPDATE SET
                    assets = excluded.assets,
                    liabilities = excluded.liabilities,
                    equity = excluded.equity,
                    current_assets = excluded.current_assets,
                    current_liab = excluded.current_liab,
                    sales = excluded.sales,
                    gross_profit = excluded.gross_profit,
                    operating_income = excluded.operating_income,
                    net_income = excluded.net_income,
                    is_consolidated = excluded.is_consolidated,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def upsert_metrics(self, metrics: Iterable[FinancialMetric]) -> int:
        """월별 밸류에이션을 (stock_code, year_month) 기준으로 upsert한다.

        한 번의 호출은 하나의 트랜잭션이다.

        Returns:
            처리한 행 수 (신규 + 갱신).
        """
        rows = [
            {
                "stock_code": m.stock_code,
                "year_month": m.year_month,
                "trade_date": m.trade_date,
                "close_price": m.close_price,
                "market_cap": m.market_cap,
                "shares_out": m.shares_out,
                "per": m.per,
                "pbr": m.pbr,
                "psr": m.psr,
                "pcr": m.pcr,
            }
            for m in metrics
        ]
        if not rows:
            return 0
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO financial_metrics
                    (stock_code, year_month, trade_date, close_price, market_cap,
                     shares_out, per, pbr, psr, pcr, updated_at)
                VALUES
                    (:stock_code, :year_month, :trade_date, :close_price, :market_cap,
                     :shares_out, :per, :pbr, :psr, :pcr, datetime('now'))
                ON CONFLICT(stock_code, year_month) DO UPDATE SET
                    trade_date = excluded.trade_date,
                    close_price = excluded.close_price,
                    market_cap = excluded.market_cap,
                    shares_out = excluded.shares_out,
                    per = excluded.per,
                    pbr = excluded.pbr,
                    psr = excluded.psr,
                    pcr = excluded.pcr,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def list_statements(self, stock_code: str) -> list[FinancialStatement]:
        """한 종목의 재무제표를 연도 오름차순으로 반환한다."""
        rows = self._connection.execute(
            "SELECT * FROM financial_statements WHERE stock_code = ? ORDER BY year, report_type",
            (stock_code,),
        ).fetchall()
        return [
            FinancialStatement(
                stock_code=r["stock_code"],
                year=r["year"],
                report_type=r["report_type"],
                assets=r["assets"],
                liabilities=r["liabilities"],
                equity=r["equity"],
                current_assets=r["current_assets"],
                current_liab=r["current_liab"],
                sales=r["sales"],
                gross_profit=r["gross_profit"],
                operating_income=r["operating_income"],
                net_income=r["net_income"],
                is_consolidated=r["is_consolidated"],
            )
            for r in rows
        ]

    def list_metrics(self, stock_code: str) -> list[FinancialMetric]:
        """한 종목의 월별 밸류에이션을 기준 월 오름차순으로 반환한다."""
        rows = self._connection.execute(
            "SELECT * FROM financial_metrics WHERE stock_code = ? ORDER BY year_month",
            (stock_code,),
        ).fetchall()
        return [
            FinancialMetric(
                stock_code=r["stock_code"],
                year_month=r["year_month"],
                trade_date=r["trade_date"],
                close_price=r["close_price"],
                market_cap=r["market_cap"],
                shares_out=r["shares_out"],
                per=r["per"],
                pbr=r["pbr"],
                psr=r["psr"],
                pcr=r["pcr"],
            )
            for r in rows
        ]
