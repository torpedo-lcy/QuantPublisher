"""Database 클래스와 init_db 진입점.

connection.py의 함수형 API(get_connection, connect, initialize_schema)를 기반으로
상태를 가지는 Database 객체와 idempotent한 init_db()를 제공한다.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from config.settings import get_settings
from quantpublisher.database.connection import connect as _connect
from quantpublisher.database.connection import initialize_schema

logger = logging.getLogger(__name__)


class Database:
    """SQLite 데이터베이스에 대한 connection/transaction 진입점.

    db_path를 지정하지 않으면 Settings.db_path를 기본값으로 사용한다.
    Connection 생성과 종료는 이 클래스가 감싸는 connect()/transaction() 안에서만
    이루어진다.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path: Path = db_path if db_path is not None else get_settings().db_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """connection을 열고 블록을 벗어나면 명시적으로 닫는다."""
        with _connect(self.db_path) as connection:
            yield connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """트랜잭션 경계를 가지는 connection을 연다.

        블록이 예외 없이 끝나면 commit하고, 예외가 발생하면 rollback한 뒤
        예외를 그대로 상위로 전달한다.
        """
        with _connect(self.db_path) as connection:
            with connection:
                yield connection


def init_db(db_path: Path) -> Path:
    """DB 파일과 기본 스키마를 초기화한다.

    상위 디렉터리가 없으면 생성하고, 이미 초기화된 DB에 대해서도
    안전하게 재호출할 수 있다 (idempotent).
    """
    database = Database(db_path)
    with database.connect() as connection:
        initialize_schema(connection)
    logger.info("init_db_completed path=%s", db_path)
    return db_path
