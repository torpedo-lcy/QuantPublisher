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
"""


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
    """기본 테이블 스키마를 생성한다 (없는 경우에만)."""
    with connection:
        connection.executescript(_SCHEMA_SQL)
    logger.info("db_schema_initialized")


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
