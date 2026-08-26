"""Application settings loaded from environment variables and an optional .env file.

Values are never hardcoded for API keys or paths that differ between
environments; see docs/DEVELOPMENT_RULE.md section 8.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


def _load_dotenv(env_file: Path) -> None:
    """Load KEY=VALUE pairs from ``env_file`` into ``os.environ``.

    Existing environment variables always take precedence over values in
    the file. Missing files are silently ignored; a missing .env is a
    normal local setup, not an error.
    """
    if not env_file.is_file():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the Quant Publisher pipeline."""

    environment: str
    data_dir: Path
    db_path: Path
    log_dir: Path
    log_level: str


def _build_settings() -> Settings:
    environment = os.environ.get("QP_ENVIRONMENT", "development")
    data_dir = Path(os.environ.get("QP_DATA_DIR", PROJECT_ROOT / "data"))
    db_path = Path(os.environ.get("QP_DB_PATH", data_dir / "quantpublisher.sqlite3"))
    log_dir = Path(os.environ.get("QP_LOG_DIR", PROJECT_ROOT / "logs"))
    log_level = os.environ.get("QP_LOG_LEVEL", "INFO")

    return Settings(
        environment=environment,
        data_dir=data_dir,
        db_path=db_path,
        log_dir=log_dir,
        log_level=log_level,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process-wide :class:`Settings` instance.

    Loads ``.env`` (if present) on first call, then reads from the
    environment. Call ``get_settings.cache_clear()`` in tests that need a
    fresh read after mutating ``os.environ``.
    """
    _load_dotenv(DEFAULT_ENV_FILE)
    return _build_settings()
