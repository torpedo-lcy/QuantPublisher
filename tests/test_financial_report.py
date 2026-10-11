from __future__ import annotations

from pathlib import Path

from quantpublisher.automation.stock_metrics import build_financial_history
from quantpublisher.database.models import FinancialStatement, Security
from quantpublisher.report import FinancialYear, StockMetrics, build_stock_report
from quantpublisher.report.chart_data import (
    build_financial_chart_data,
    write_financial_chart_json,
)
from quantpublisher.report.markdown import render_stock_report_markdown

JO = 1_000_000_000_000
EOK = 100_000_000


def _statement(year: int, **values: float | int | None) -> FinancialStatement:
    return FinancialStatement("005930", year, "11011", is_consolidated=1, **values)  # type: ignore[arg-type]


def _report(history: tuple[FinancialYear, ...], chart: bool = False):
    security = Security(stock_code="005930", name="Samsung Electronics", market="KOSPI")
    return build_stock_report(
        security, StockMetrics(), financial_history=history, has_financial_chart=chart
    )


def test_build_financial_history_computes_ratios_and_orders_by_year() -> None:
    statements = [
        _statement(2025, sales=200.0, operating_income=20.0, net_income=10.0, equity=100.0),
        _statement(2024, sales=100.0, operating_income=5.0, net_income=2.0, equity=50.0),
    ]

    history = build_financial_history(statements)

    assert [h.year for h in history] == [2024, 2025]
    assert history[1].operating_margin == 10.0
    assert history[1].roe == 10.0


def test_build_financial_history_limits_years_and_skips_empty_years() -> None:
    statements = [_statement(2010 + i, sales=float(i + 1)) for i in range(12)]
    statements.append(_statement(2030))  # 값이 전혀 없는 해

    history = build_financial_history(statements, max_years=8)

    assert len(history) == 8
    assert history[-1].year == 2021
    assert all(h.year != 2030 for h in history)


def test_build_financial_history_ignores_non_annual_rows() -> None:
    quarterly = FinancialStatement("005930", 2025, "11013", sales=1.0)

    assert build_financial_history([quarterly]) == ()


def test_markdown_formats_amounts_and_summarizes_performance() -> None:
    history = (
        FinancialYear(2024, 1, 300 * JO // 1, 30 * JO, -2 * JO, 10.0, 5.0),
        FinancialYear(2025, 1, 330 * JO, 45 * JO, 3000 * EOK, 13.64, 7.0),
    )

    markdown = render_stock_report_markdown(_report(history))

    assert "## 재무 시계열" in markdown
    assert "| 2025 | 연결 | 330.00조원 | 45.00조원 | 3,000억원 | 13.64 | 7.00 |" in markdown
    assert "- 기준: 2025년 연간, 연결" in markdown
    assert "- 매출액: 2025년 330.00조원 (전년 300.00조원 대비 +10.00%)" in markdown
    assert "- 영업이익: 2025년 45.00조원 (전년 30.00조원 대비 +50.00%)" in markdown
    assert "- 순이익: 2025년 3,000억원 (전년 -2.00조원, 흑자전환)" in markdown
    assert "- 영업이익률: 13.64% (전년 10.00%, +3.64%p)" in markdown


def test_markdown_skips_comparison_when_basis_differs_or_year_missing() -> None:
    different_basis = (
        FinancialYear(2024, 0, 100.0 * EOK),
        FinancialYear(2025, 1, 200.0 * EOK),
    )
    gap_year = (
        FinancialYear(2022, 1, 100.0 * EOK),
        FinancialYear(2025, 1, 200.0 * EOK),
    )

    for history in (different_basis, gap_year):
        markdown = render_stock_report_markdown(_report(history))

        assert "비교할 수 없음" in markdown
        assert "- 매출액: 2025년 200억원" in markdown
        assert "- 매출액: 2025년 200억원\n" in markdown  # 증감 괄호 없이 금액만
        assert "(전년" not in markdown


def test_markdown_shows_na_for_missing_amounts_and_omits_section_without_history() -> None:
    history = (FinancialYear(2025, None, None, 5.0 * EOK),)

    markdown = render_stock_report_markdown(_report(history))

    assert "| 2025 | - | N/A | 5억원 | N/A | N/A | N/A |" in markdown
    assert "- 매출액" not in markdown  # 값이 없는 항목은 요약에서 뺀다
    assert "## 재무 시계열" not in render_stock_report_markdown(_report(()))
    assert "financialchart" not in markdown


def test_markdown_includes_financial_chart_shortcode_only_when_flagged() -> None:
    history = (FinancialYear(2024, 1, 1.0), FinancialYear(2025, 1, 2.0))

    assert '{{< financialchart code="005930" >}}' in render_stock_report_markdown(
        _report(history, chart=True)
    )
    assert "financialchart" not in render_stock_report_markdown(_report(history))


def test_build_financial_chart_data_uses_eok_and_needs_two_years() -> None:
    history = (
        FinancialYear(2024, 1, 3 * JO, None, -50 * EOK),
        FinancialYear(2025, 1, 4 * JO, 5 * EOK, 60 * EOK),
    )

    data = build_financial_chart_data("005930", history)

    assert data == {
        "code": "005930",
        "y": [2024, 2025],
        "s": [30000, 40000],
        "o": [None, 5],
        "n": [-50, 60],
    }
    assert build_financial_chart_data("005930", history[:1]) is None


def test_write_financial_chart_json_skips_unchanged_and_insufficient(tmp_path: Path) -> None:
    history = (FinancialYear(2024, 1, 1.0), FinancialYear(2025, 1, 2.0))
    path = write_financial_chart_json("005930", history, tmp_path)
    assert path == tmp_path / "005930.json"
    before = path.stat().st_mtime_ns

    write_financial_chart_json("005930", history, tmp_path)

    assert path.stat().st_mtime_ns == before
    assert write_financial_chart_json("000660", history[:1], tmp_path) is None
    assert not (tmp_path / "000660.json").exists()
