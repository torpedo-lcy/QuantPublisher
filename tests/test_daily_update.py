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
from quantpublisher.database.financial_repository import FinancialRepository
from quantpublisher.database.models import FinancialStatement, PriceDaily
from quantpublisher.database.price_repository import PriceRepository
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


def test_run_daily_update_does_not_touch_report_files_on_rerun(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    records = _load_fixture("krx_listing_sample.json")
    _patch_fdr_success(monkeypatch, records)
    content_dir = tmp_path / "content" / "stocks"

    run_daily_update(content_dir=content_dir, settings=settings)
    before = {p.name: p.stat().st_mtime_ns for p in content_dir.glob("*.md")}
    run_daily_update(content_dir=content_dir, settings=settings)
    after = {p.name: p.stat().st_mtime_ns for p in content_dir.glob("*.md")}

    assert before and before == after


def test_run_daily_update_uses_latest_trade_date_as_data_date(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    records = _load_fixture("krx_listing_sample.json")
    _patch_fdr_success(monkeypatch, records)
    content_dir = tmp_path / "content" / "stocks"
    run_daily_update(content_dir=content_dir, settings=settings)
    stock_code = next(iter(sorted(p.stem for p in content_dir.glob("*.md"))))
    with Database(settings.db_path).connect() as connection:
        PriceRepository(connection).upsert_many(
            [
                PriceDaily(stock_code, "2026-07-30", 1.0, 2.0, 0.5, 1.5, 10.0),
                PriceDaily(stock_code, "2026-07-31", 1.0, 2.0, 0.5, 1.5, 10.0),
            ]
        )

    run_daily_update(content_dir=content_dir, settings=settings)

    text = (content_dir / f"{stock_code}.md").read_text(encoding="utf-8")
    assert 'date: "2026-07-31"' in text
    assert "데이터 기준일: 2026-07-31" in text


def test_run_daily_update_writes_price_chart_json_and_shortcode(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    records = _load_fixture("krx_listing_sample.json")
    _patch_fdr_success(monkeypatch, records)
    content_dir = tmp_path / "website" / "content" / "stocks"
    chart_dir = tmp_path / "website" / "static" / "charts" / "prices"
    run_daily_update(content_dir=content_dir, settings=settings)
    codes = sorted(p.stem for p in content_dir.glob("*.md"))
    with_prices, without_prices = codes[0], codes[1]
    with Database(settings.db_path).connect() as connection:
        PriceRepository(connection).upsert_many(
            [PriceDaily(with_prices, "2026-07-31", 1.0, 2.0, 0.5, 1.5, 10.0)]
        )

    run_daily_update(content_dir=content_dir, settings=settings)

    # chart_dir를 지정하지 않아도 content_dir 기준 website/static/charts/prices에 생성된다.
    assert (chart_dir / f"{with_prices}.json").exists()
    assert not (chart_dir / f"{without_prices}.json").exists()
    with_text = (content_dir / f"{with_prices}.md").read_text(encoding="utf-8")
    without_text = (content_dir / f"{without_prices}.md").read_text(encoding="utf-8")
    assert f'{{{{< pricechart code="{with_prices}" >}}}}' in with_text
    assert "pricechart" not in without_text


def test_run_daily_update_writes_financial_section_and_chart_json(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    records = _load_fixture("krx_listing_sample.json")
    _patch_fdr_success(monkeypatch, records)
    content_dir = tmp_path / "website" / "content" / "stocks"
    chart_dir = tmp_path / "website" / "static" / "charts" / "financials"
    run_daily_update(content_dir=content_dir, settings=settings)
    codes = sorted(p.stem for p in content_dir.glob("*.md"))
    full, single, none = codes[0], codes[1], codes[2]
    with Database(settings.db_path).connect() as connection:
        FinancialRepository(connection).upsert_statements(
            [
                FinancialStatement(full, 2024, "11011", sales=1e12, is_consolidated=1),
                FinancialStatement(full, 2025, "11011", sales=2e12, is_consolidated=1),
                FinancialStatement(single, 2025, "11011", sales=2e12, is_consolidated=1),
            ]
        )

    run_daily_update(content_dir=content_dir, settings=settings)

    full_text = (content_dir / f"{full}.md").read_text(encoding="utf-8")
    single_text = (content_dir / f"{single}.md").read_text(encoding="utf-8")
    none_text = (content_dir / f"{none}.md").read_text(encoding="utf-8")
    assert (chart_dir / f"{full}.json").exists()
    assert f'{{{{< financialchart code="{full}" >}}}}' in full_text
    assert "+100.00%" in full_text
    # 한 해만 있으면 표와 요약은 있지만 차트는 만들지 않는다.
    assert "## 재무 시계열" in single_text
    assert not (chart_dir / f"{single}.json").exists()
    assert "financialchart" not in single_text
    assert "## 재무 시계열" not in none_text


def test_run_daily_update_uses_settings_db_path_by_default(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    records = _load_fixture("krx_listing_sample.json")
    _patch_fdr_success(monkeypatch, records)
    content_dir = tmp_path / "content" / "stocks"

    run_daily_update(content_dir=content_dir, settings=settings)

    assert settings.db_path.exists()
