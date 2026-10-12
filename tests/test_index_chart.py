from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from quantpublisher.crawler.index_chart import IndexFetchError, update_index_charts
from quantpublisher.report.chart_data import (
    CHART_MAX_ROWS,
    build_index_chart_data,
    write_index_chart_json,
)


def test_build_index_chart_data_uses_epoch_days_and_compact_numbers() -> None:
    data = build_index_chart_data("KOSPI", [("1970-01-02", 2650.0), ("1970-01-05", 2651.25)])

    assert data == {"code": "KOSPI", "t": [1, 4], "c": [2650, 2651.25]}
    assert isinstance(data["c"][0], int)  # type: ignore[index]


def test_build_index_chart_data_keeps_only_recent_rows_and_none_when_empty() -> None:
    rows = [(date.fromordinal(date(2024, 1, 1).toordinal() + i).isoformat(), 100.0 + i) for i in range(CHART_MAX_ROWS + 5)]

    data = build_index_chart_data("KOSDAQ", rows)

    assert data is not None
    assert len(data["t"]) == CHART_MAX_ROWS  # type: ignore[arg-type]
    assert data["c"][-1] == rows[-1][1]  # type: ignore[index]
    assert build_index_chart_data("KOSDAQ", []) is None


def test_write_index_chart_json_skips_rewrite_and_empty(tmp_path: Path) -> None:
    rows = [("2026-10-08", 2650.0)]

    path = write_index_chart_json("KOSPI", rows, tmp_path)
    assert path == tmp_path / "KOSPI.json"
    assert json.loads(path.read_text(encoding="utf-8"))["code"] == "KOSPI"

    mtime = path.stat().st_mtime_ns
    write_index_chart_json("KOSPI", rows, tmp_path)
    assert path.stat().st_mtime_ns == mtime
    assert write_index_chart_json("KOSDAQ", [], tmp_path) is None
    assert not (tmp_path / "KOSDAQ.json").exists()


def test_update_index_charts_continues_after_one_index_fails(tmp_path: Path) -> None:
    def fetch(symbol: str, start: date) -> list[tuple[str, float]]:
        if symbol == "KS11":
            raise IndexFetchError("boom")
        return [("2026-10-08", 800.0)]

    updated = update_index_charts(tmp_path, fetch=fetch, today=date(2026, 10, 12))

    assert updated == 1
    assert not (tmp_path / "KOSPI.json").exists()
    assert (tmp_path / "KOSDAQ.json").exists()


def test_markdown_shortcode_passes_market_only_for_indexed_markets() -> None:
    from quantpublisher.database.models import Security
    from quantpublisher.report import StockMetrics, build_stock_report
    from quantpublisher.report.markdown import render_stock_report_markdown

    def render(market: str) -> str:
        report = build_stock_report(
            Security("005930", "Samsung", market), StockMetrics(), has_price_chart=True
        )
        return render_stock_report_markdown(report)

    assert '{{< pricechart code="005930" market="KOSDAQ" >}}' in render("KOSDAQ")
    assert '{{< pricechart code="005930" >}}' in render("KONEX")
