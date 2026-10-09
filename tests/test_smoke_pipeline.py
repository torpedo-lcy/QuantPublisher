"""MVP 전체 파이프라인 smoke test (Task 012).

PROJECT_SPEC.md 10절의 성공 기준 중 Python이 담당하는 구간을 네트워크
없이 재현한다.

    데이터 수집 -> SQLite 저장 -> Markdown(Hugo content) 생성

- FinanceDataReader는 test_daily_update.py와 동일한 방식으로 monkeypatch한다.
- 모든 출력은 tmp_path 아래에만 쓴다. 실제 data/, website/ 는 건드리지 않는다.
- Hugo build, git push, GitHub Actions는 외부 도구/네트워크가 필요하므로
  자동 테스트가 아니라 docs/OPERATIONS.md의 수동 점검 절차로 확인한다.
"""

from __future__ import annotations

import json
import os
import plistlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from config.settings import PROJECT_ROOT, Settings
from quantpublisher.automation.daily_update import DailyUpdateError, run_daily_update
from quantpublisher.database.core import Database
from quantpublisher.database.security_repository import SecurityRepository

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# 재생성할 때마다 값이 바뀌는 줄. 나머지 내용은 입력이 같으면 동일해야 한다.
_VOLATILE_LINE_PREFIXES = ("date:", "- 생성 시각:")


class _FakeDataFrame:
    def __init__(self, records: list[dict]) -> None:
        self._records = records

    def to_dict(self, orient: str) -> list[dict]:
        assert orient == "records"
        return self._records


def _load_listing_fixture() -> list[dict]:
    with (FIXTURES_DIR / "krx_listing_sample.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def _patch_fdr_success(monkeypatch: pytest.MonkeyPatch) -> None:
    records = _load_listing_fixture()
    fake_fdr = SimpleNamespace(StockListing=lambda market: _FakeDataFrame(records))
    monkeypatch.setitem(sys.modules, "FinanceDataReader", fake_fdr)


def _patch_fdr_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_error(market: str):
        raise RuntimeError("network unreachable")

    fake_fdr = SimpleNamespace(StockListing=_raise_error)
    monkeypatch.setitem(sys.modules, "FinanceDataReader", fake_fdr)


def _stable_lines(markdown: str) -> list[str]:
    return [
        line
        for line in markdown.splitlines()
        if not line.startswith(_VOLATILE_LINE_PREFIXES)
    ]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "smoke.sqlite3",
        log_dir=tmp_path / "logs",
        log_level="INFO",
    )


def test_all_layers_expose_public_entry_points():
    from quantpublisher.analysis import metrics
    from quantpublisher.backtest import run_backtest
    from quantpublisher.crawler.krx_listing import collect_krx_listing
    from quantpublisher.database.core import init_db
    from quantpublisher.report import build_stock_report, write_stock_report_markdown

    assert callable(metrics.calculate_daily_return)
    assert callable(run_backtest)
    assert callable(collect_krx_listing)
    assert callable(init_db)
    assert callable(build_stock_report)
    assert callable(write_stock_report_markdown)


def test_pipeline_produces_hugo_content_for_every_stored_security(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _patch_fdr_success(monkeypatch)
    content_dir = tmp_path / "website" / "content" / "stocks"

    result = run_daily_update(content_dir=content_dir, settings=settings)

    with Database(settings.db_path).connect() as connection:
        stored = SecurityRepository(connection).list_all()
    assert result.securities_collected == len(stored) > 0
    assert result.reports_generated == len(stored)

    for security in stored:
        text = (content_dir / f"{security.stock_code}.md").read_text(encoding="utf-8")
        lines = text.splitlines()
        # Hugo front matter: 첫 줄 '---', 이후 다시 '---'로 닫힌다.
        assert lines[0] == "---"
        closing = lines.index("---", 1)
        front_matter = "\n".join(lines[1:closing])
        assert f'stock_code: "{security.stock_code}"' in front_matter
        assert f'market: "{security.market}"' in front_matter
        assert "draft: false" in front_matter
        assert "date:" in front_matter
        assert security.name in text


def test_pipeline_does_not_publish_rows_that_failed_validation(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _patch_fdr_success(monkeypatch)
    content_dir = tmp_path / "content" / "stocks"

    run_daily_update(content_dir=content_dir, settings=settings)

    generated_codes = {p.stem for p in content_dir.glob("*.md")}
    # fixture의 잘못된 행: 코드 길이 오류(12345), 시장 구분 오류(999999)
    assert "12345" not in generated_codes
    assert "999999" not in generated_codes
    assert "005930" in generated_codes


def test_pipeline_rerun_changes_only_timestamp_lines(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """재실행해도 생성 시각을 제외한 내용은 동일하다.

    생성 시각(front matter의 date, 본문의 '생성 시각')은 실행마다 바뀐다.
    이 때문에 실제 운영에서는 매 실행마다 모든 content 파일이 git diff에
    잡힌다. docs/OPERATIONS.md의 '알려진 제한'을 참고한다.
    """
    _patch_fdr_success(monkeypatch)
    content_dir = tmp_path / "content" / "stocks"

    run_daily_update(content_dir=content_dir, settings=settings)
    first = {p.name: _stable_lines(p.read_text(encoding="utf-8")) for p in content_dir.glob("*.md")}
    run_daily_update(content_dir=content_dir, settings=settings)
    second = {p.name: _stable_lines(p.read_text(encoding="utf-8")) for p in content_dir.glob("*.md")}

    assert first == second


def test_pipeline_failure_keeps_existing_content_untouched(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    content_dir = tmp_path / "content" / "stocks"
    content_dir.mkdir(parents=True)
    previous = content_dir / "005930.md"
    previous.write_text("previous good report", encoding="utf-8")

    _patch_fdr_failure(monkeypatch)
    with pytest.raises(DailyUpdateError):
        run_daily_update(content_dir=content_dir, settings=settings)

    # 불완전한 데이터로 리포트를 덮어쓰지 않는다 (ARCHITECTURE.md 12절).
    assert previous.read_text(encoding="utf-8") == "previous good report"
    assert [p.name for p in content_dir.iterdir()] == ["005930.md"]


def test_operations_files_are_consistent():
    script = PROJECT_ROOT / "scripts" / "daily_update.sh"
    plist_path = PROJECT_ROOT / "scripts" / "com.quantpublisher.dailyupdate.plist"
    workflow = PROJECT_ROOT / ".github" / "workflows" / "hugo.yml"

    assert script.exists()
    assert os.access(script, os.X_OK), "scripts/daily_update.sh에 실행 권한이 없습니다."

    with plist_path.open("rb") as f:
        plist = plistlib.load(f)
    assert plist["Label"] == "com.quantpublisher.dailyupdate"
    assert plist["ProgramArguments"][-1].endswith("scripts/daily_update.sh")
    assert plist["StartCalendarInterval"]["Hour"] in range(24)

    workflow_text = workflow.read_text(encoding="utf-8")
    assert "./website" in workflow_text
    assert "actions/deploy-pages" in workflow_text

    for doc in ("PROJECT_SPEC.md", "ARCHITECTURE.md", "DEVELOPMENT_RULE.md",
                "AUTOMATION.md", "OPERATIONS.md"):
        assert (PROJECT_ROOT / "docs" / doc).exists(), f"docs/{doc} 없음"
