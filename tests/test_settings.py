import os

import pytest

from config.settings import PROJECT_ROOT, Settings, _load_dotenv, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Ensure each test observes a fresh Settings build."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_get_settings_returns_defaults_when_env_vars_unset(monkeypatch):
    monkeypatch.delenv("QP_ENVIRONMENT", raising=False)
    monkeypatch.delenv("QP_DATA_DIR", raising=False)
    monkeypatch.delenv("QP_DB_PATH", raising=False)
    monkeypatch.delenv("QP_LOG_DIR", raising=False)
    monkeypatch.delenv("QP_LOG_LEVEL", raising=False)

    settings = get_settings()

    assert settings == Settings(
        environment="development",
        data_dir=PROJECT_ROOT / "data",
        db_path=PROJECT_ROOT / "data" / "quantpublisher.sqlite3",
        log_dir=PROJECT_ROOT / "logs",
        log_level="INFO",
    )


def test_get_settings_reads_environment_variables(monkeypatch):
    monkeypatch.setenv("QP_ENVIRONMENT", "production")
    monkeypatch.setenv("QP_LOG_LEVEL", "DEBUG")

    settings = get_settings()

    assert settings.environment == "production"
    assert settings.log_level == "DEBUG"


def test_load_dotenv_does_not_override_existing_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("QP_LOG_LEVEL", "WARNING")
    env_file = tmp_path / ".env"
    env_file.write_text("QP_LOG_LEVEL=DEBUG\nQP_ENVIRONMENT=staging\n", encoding="utf-8")

    _load_dotenv(env_file)

    assert os.environ["QP_LOG_LEVEL"] == "WARNING"  # existing value wins
    assert os.environ["QP_ENVIRONMENT"] == "staging"  # new value loaded


def test_load_dotenv_ignores_missing_file(tmp_path):
    missing_file = tmp_path / "does_not_exist.env"

    # Should not raise.
    _load_dotenv(missing_file)
