from __future__ import annotations

from pathlib import Path

from quantpublisher.database.models import Security
from quantpublisher.report import (
    StockMetrics,
    StockReport,
    build_stock_report,
    render_stock_report_markdown,
    write_stock_report_markdown,
)


def _sample_report() -> StockReport:
    security = Security(stock_code="005930", name="Samsung Electronics", market="KOSPI")
    metrics = StockMetrics(roe=10.0, eps=1000.0, per=12.345)
    return build_stock_report(security, metrics, generated_at="2026-01-01T00:00:00+00:00")


def test_render_stock_report_markdown_starts_with_front_matter() -> None:
    markdown = render_stock_report_markdown(_sample_report())

    lines = markdown.splitlines()
    assert lines[0] == "---"
    assert "---" in lines[1:]


def test_render_stock_report_markdown_front_matter_contains_identity() -> None:
    markdown = render_stock_report_markdown(_sample_report())

    front_matter = markdown.split("---")[1]
    assert 'stock_code: "005930"' in front_matter
    assert 'market: "KOSPI"' in front_matter
    assert 'date: "2026-01-01T00:00:00+00:00"' in front_matter


def test_render_stock_report_markdown_contains_stock_name() -> None:
    markdown = render_stock_report_markdown(_sample_report())

    assert "Samsung Electronics" in markdown


def test_render_stock_report_markdown_contains_key_metrics() -> None:
    markdown = render_stock_report_markdown(_sample_report())

    assert "ROE" in markdown
    assert f"{10.0:.2f}" in markdown
    assert "PER" in markdown
    assert f"{12.345:.2f}" in markdown


def test_render_stock_report_markdown_uses_na_for_missing_metrics() -> None:
    markdown = render_stock_report_markdown(_sample_report())

    # roa, bps, pbr 등은 설정하지 않았으므로 N/A로 표시되어야 한다.
    assert "N/A" in markdown


def test_write_stock_report_markdown_creates_file(tmp_path: Path) -> None:
    report = _sample_report()
    output_dir = tmp_path / "reports"

    file_path = write_stock_report_markdown(report, output_dir)

    assert file_path.exists()
    assert file_path.name == "005930.md"
    content = file_path.read_text(encoding="utf-8")
    assert content == render_stock_report_markdown(report)


def test_write_stock_report_markdown_creates_missing_output_dir(tmp_path: Path) -> None:
    report = _sample_report()
    output_dir = tmp_path / "nested" / "reports"

    write_stock_report_markdown(report, output_dir)

    assert output_dir.exists()


def test_write_stock_report_markdown_overwrites_existing_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "reports"
    security = Security(stock_code="005930", name="Samsung Electronics", market="KOSPI")

    first = build_stock_report(security, StockMetrics(roe=5.0))
    second = build_stock_report(security, StockMetrics(roe=99.0))

    write_stock_report_markdown(first, output_dir)
    file_path = write_stock_report_markdown(second, output_dir)

    content = file_path.read_text(encoding="utf-8")
    assert f"{99.0:.2f}" in content
    assert f"{5.0:.2f}" not in content
