"""daily_update 자동화 진입점 테스트.

- fetch_krx_listing이 호출하는 FinanceDataReader는 네트워크를 타지 않도록
  monkeypatch로 대체한다 (test_krx_listing.py와 동일한 패턴).
- 파이프라인 성공 시 DB에 종목이 저장되고, 종목별 Markdown 리포트가
  content_dir에 생성되는지 확인한다.
- crawler 단계 실패 시 리포트 생성 단계가 실행되지 않는지 확인한다
  (ARCHITECTURE.md 12절).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from config.settings import Settings
from quantpublisher.automation.daily_update import (
    DailyUpdateError,
    DailyUpdateResult,
    run_daily_update,
)
from quantpublisher.database.core import Database
from quantpublisher.database.security_repository import SecurityRepository

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class _FakeDataFrame:
    def __init__(self, records: list[dict]) -> None:
        self._records = records

    def to_dict(self, orient: str) -> list[dict]:
        assert orient == "records"
        return self._records


def _load_fixture(name: str) -> list[dict]:
    with (FIXTURES_DIR / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def _patch_fdr_success(monkeypatch: pytest.MonkeyPatch, records: list[dict]) -> None:
    fake_fdr = SimpleNamespace(StockListing=lambda market: _FakeDataFrame(records))
    monkeypatch.setitem(sys.modules, "FinanceDataReader", fake_fdr)


def _patch_fdr_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_market_error(market: str):
        raise RuntimeError("network unreachable")

    fake_fdr = SimpleNamespace(StockListing=_raise_market_error)
    monkeypatch.setitem(sys.modules, "FinanceDataReader", fake_fdr)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "quantpublisher_test.sqlite3",
        log_dir=tmp_path / "logs",
        log_level="INFO",
    )


def test_run_daily_update_succeeds_end_to_end(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    records = _load_fixture("krx_listing_sample.json")
    _patch_fdr_success(monkeypatch, records)
    content_dir = tmp_path / "content" / "stocks"

    result = run_daily_update(content_dir=content_dir, settings=settings)

    assert isinstance(result, DailyUpdateResult)
    assert result.securities_collected > 0
    assert result.reports_generated == result.securities_collected
    assert result.elapsed_seconds >= 0

    # DB에 실제로 종목이 저장되었는지 확인한다.
    database = Database(settings.db_path)
    with database.connect() as connection:
        stored = SecurityRepository(connection).list_all()
    assert len(stored) == result.securities_collected

    # 종목별 Markdown 리포트가 생성되었는지 확인한다.
    generated_files = sorted(p.name for p in content_dir.glob("*.md"))
    expected_files = sorted(f"{s.stock_code}.md" for s in stored)
    assert generated_files == expected_files


def test_run_daily_update_report_contains_identity_and_na_metrics(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    records = _load_fixture("krx_listing_sample.json")
    _patch_fdr_success(monkeypatch, records)
    content_dir = tmp_path / "content" / "stocks"

    run_daily_update(content_dir=content_dir, settings=settings)

    samsung_report = (content_dir / "005930.md").read_text(encoding="utf-8")
    assert 'stock_code: "005930"' in samsung_report
    assert "N/A" in samsung_report  # 아직 재무 데이터 수집 기능이 없으므로 모든 지표가 N/A


def test_run_daily_update_stops_before_report_generation_when_crawler_fails(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _patch_fdr_failure(monkeypatch)
    content_dir = tmp_path / "content" / "stocks"

    with pytest.raises(DailyUpdateError):
        run_daily_update(content_dir=content_dir, settings=settings)

    # report 생성 단계까지 도달하지 않았으므로 content_dir가 생성되지 않는다.
    assert not content_dir.exists()

    # DB에도 종목이 저장되지 않는다.
    database = Database(settings.db_path)
    with database.connect() as connection:
        assert SecurityRepository(connection).list_all() == []


def test_run_daily_update_is_idempotent_when_run_twice(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    records = _load_fixture("krx_listing_sample.json")
    _patch_fdr_success(monkeypatch, records)
    content_dir = tmp_path / "content" / "stocks"

    first = run_daily_update(content_dir=content_dir, settings=settings)
    second = run_daily_update(content_dir=content_dir, settings=settings)

    assert first.securities_collected == second.securities_collected
    assert first.reports_generated == second.reports_generated

    database = Database(settings.db_path)
    with database.connect() as connection:
        stored = SecurityRepository(connection).list_all()
    assert len(stored) == first.securities_collected  # 중복 저장되지 않는다.


def test_run_daily_update_uses_settings_db_path_by_default(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    records = _load_fixture("krx_listing_sample.json")
    _patch_fdr_success(monkeypatch, records)
    content_dir = tmp_path / "content" / "stocks"

    run_daily_update(content_dir=content_dir, settings=settings)

    assert settings.db_path.exists()
