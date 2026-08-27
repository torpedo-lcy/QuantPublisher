"""프로젝트 설정.

민감한 값(API Key 등)은 환경 변수 또는 .env 파일에서 읽는다.
코드에 하드코딩하지 않는다.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

DATA_DIR: Path = PROJECT_ROOT / "data"
DEFAULT_DB_PATH: Path = DATA_DIR / "quantpublisher.sqlite3"


def get_db_path() -> Path:
    """DB 경로를 반환한다.

    환경 변수 QUANTPUBLISHER_DB_PATH가 설정되어 있으면 이를 사용하고,
    그렇지 않으면 기본 경로를 사용한다.
    """
    override = os.environ.get("QUANTPUBLISHER_DB_PATH")
    if override:
        return Path(override)
    return DEFAULT_DB_PATH
