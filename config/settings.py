"""프로젝트 설정.

민감한 값(API Key 등)은 환경 변수 또는 .env 파일에서 읽는다.
코드에 하드코딩하지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

_ENV_FILE_NAME = ".env"


@dataclass(frozen=True, slots=True)
class Settings:
    """애플리케이션 설정 값 모음.

    Attributes:
        environment: 실행 환경 ("development", "production" 등).
        data_dir: 원천/가공 데이터 저장 디렉터리.
        db_path: SQLite DB 파일 경로.
        log_dir: 로그 파일 디렉터리.
        log_level: 로깅 레벨 (예: "INFO", "DEBUG").
    """

    environment: str
    data_dir: Path
    db_path: Path
    log_dir: Path
    log_level: str


def _load_dotenv(path: Path) -> None:
    """.env 파일을 읽어 os.environ에 값을 채운다.

    이미 설정된 환경 변수는 덮어쓰지 않는다.
    파일이 없으면 아무 작업도 하지 않는다.
    """
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


@lru_cache
def get_settings() -> Settings:
    """환경 변수(및 .env)로부터 Settings를 생성한다.

    결과는 캐시된다. 테스트에서는 get_settings.cache_clear()로 초기화한다.
    """
    _load_dotenv(PROJECT_ROOT / _ENV_FILE_NAME)

    data_dir = Path(os.environ.get("QP_DATA_DIR", str(PROJECT_ROOT / "data")))
    default_db_path = PROJECT_ROOT / "data" / "quantpublisher.sqlite3"
    default_log_dir = PROJECT_ROOT / "logs"

    return Settings(
        environment=os.environ.get("QP_ENVIRONMENT", "development"),
        data_dir=data_dir,
        db_path=Path(os.environ.get("QP_DB_PATH", str(default_db_path))),
        log_dir=Path(os.environ.get("QP_LOG_DIR", str(default_log_dir))),
        log_level=os.environ.get("QP_LOG_LEVEL", "INFO"),
    )
