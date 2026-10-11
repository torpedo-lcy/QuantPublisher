"""company_profiles 테이블에 대한 데이터 접근을 담당한다 (Task 019).

SQL은 이 모듈에 모으고, 수집/파싱/표현 로직은 포함하지 않는다.
"""

from __future__ import annotations

import logging
import sqlite3

from quantpublisher.database.models import CompanyProfile

logger = logging.getLogger(__name__)

_COLUMNS = (
    "stock_code",
    "induty_code",
    "established_date",
    "ceo_name",
    "address",
    "homepage",
    "fiscal_month",
    "business_summary",
    "history_json",
    "report_rcept_no",
    "report_year",
)


class CompanyProfileRepository:
    """company_profiles 테이블 Repository.

    호출자가 sqlite3.Connection의 생성과 종료를 책임진다.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(self, profile: CompanyProfile) -> None:
        """기업 개요를 stock_code 기준으로 upsert한다.

        새 값이 None이면 기존 값도 None으로 덮어쓴다 (원천에서 사라진 값이
        오래된 채로 남지 않게 하기 위함). 한 번의 호출은 하나의 트랜잭션이다.
        """
        values = {name: getattr(profile, name) for name in _COLUMNS}
        assignments = ", ".join(f"{name} = excluded.{name}" for name in _COLUMNS[1:])
        with self._connection:
            self._connection.execute(
                f"""
                INSERT INTO company_profiles ({", ".join(_COLUMNS)}, updated_at)
                VALUES ({", ".join(":" + name for name in _COLUMNS)}, datetime('now'))
                ON CONFLICT(stock_code) DO UPDATE SET
                    {assignments},
                    updated_at = excluded.updated_at
                """,
                values,
            )

    def get(self, stock_code: str) -> CompanyProfile | None:
        """한 종목의 기업 개요를 반환한다. 없으면 None."""
        row = self._connection.execute(
            "SELECT * FROM company_profiles WHERE stock_code = ?", (stock_code,)
        ).fetchone()
        return _row_to_profile(row) if row is not None else None

    def list_all(self) -> dict[str, CompanyProfile]:
        """전체 기업 개요를 종목코드로 찾을 수 있게 반환한다 (리포트 생성용)."""
        rows = self._connection.execute("SELECT * FROM company_profiles").fetchall()
        return {row["stock_code"]: _row_to_profile(row) for row in rows}

    def list_stock_codes(self) -> set[str]:
        """기업 개요가 이미 저장된 종목코드 집합을 반환한다 (수집 재시작용)."""
        rows = self._connection.execute("SELECT stock_code FROM company_profiles").fetchall()
        return {row["stock_code"] for row in rows}


def _row_to_profile(row: sqlite3.Row) -> CompanyProfile:
    return CompanyProfile(**{name: row[name] for name in _COLUMNS})
