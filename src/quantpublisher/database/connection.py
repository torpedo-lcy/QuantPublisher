"""SQLite connection 관리 모듈.

Connection 생성/종료와 스키마 초기화만 담당한다.
분석 로직이나 외부 API 호출은 포함하지 않는다.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS securities (
    stock_code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prices_daily (
    stock_code  TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (stock_code, trade_date),
    FOREIGN KEY (stock_code) REFERENCES securities(stock_code)
);

-- 연간 재무제표 (Task 014). report_type: '11011'=연간만 저장한다.
CREATE TABLE IF NOT EXISTS financial_statements (
    stock_code       TEXT NOT NULL,
    year             INTEGER NOT NULL,
    report_type      TEXT NOT NULL,   -- '11011'=연간, '11012'=반기, '11013'=1분기, '11014'=3분기
    assets           REAL,
    liabilities      REAL,
    equity           REAL,
    current_assets   REAL,
    current_liab     REAL,
    sales            REAL,
    gross_profit     REAL,
    operating_income REAL,
    net_income       REAL,
    is_consolidated  INTEGER,
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (stock_code, year, report_type),
    FOREIGN KEY (stock_code) REFERENCES securities(stock_code)
);

-- 월별 밸류에이션 (Task 014). 원천은 외부 quant.db의 market_data.
CREATE TABLE IF NOT EXISTS financial_metrics (
    stock_code   TEXT NOT NULL,
    year_month   TEXT NOT NULL,       -- YYYY-MM
    trade_date   TEXT,
    close_price  REAL,
    market_cap   REAL,
    shares_out   REAL,
    per          REAL,
    pbr          REAL,
    psr          REAL,
    pcr          REAL,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (stock_code, year_month),
    FOREIGN KEY (stock_code) REFERENCES securities(stock_code)
);
"""

# 기존 DB를 깨뜨리지 않고 추가하는 컬럼: (테이블, 컬럼, 타입).
# CREATE TABLE IF NOT EXISTS는 이미 존재하는 테이블을 바꾸지 못하므로
# ALTER TABLE ... ADD COLUMN으로 별도 처리한다.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("securities", "corp_code", "TEXT"),  # DART 고유번호 8자리 (nullable)
)


def get_connection(db_path: Path) -> sqlite3.Connection:
    """지정된 경로의 SQLite DB에 연결한다.

    상위 디렉터리가 없으면 생성한다. foreign_keys pragma를 활성화한다.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    logger.info("db_connection_opened path=%s", db_path)
    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    """기본 테이블 스키마를 생성하고, 추가 컬럼이 없으면 덧붙인다 (idempotent)."""
    with connection:
        connection.executescript(_SCHEMA_SQL)
        for table, column, column_type in _ADDED_COLUMNS:
            _ensure_column(connection, table, column, column_type)
    logger.info("db_schema_initialized")


def _ensure_column(
    connection: sqlite3.Connection, table: str, column: str, column_type: str
) -> None:
    """테이블에 컬럼이 없을 때만 ALTER TABLE ... ADD COLUMN을 실행한다."""
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column in existing:
        return
    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
    logger.info("db_column_added table=%s column=%s", table, column)


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """with 블록 안에서 사용할 수 있는 connection 컨텍스트 매니저.

    블록을 벗어날 때 connection을 명시적으로 닫는다.
    """
    connection = get_connection(db_path)
    try:
        yield connection
    finally:
        connection.close()
        logger.info("db_connection_closed path=%s", db_path)
