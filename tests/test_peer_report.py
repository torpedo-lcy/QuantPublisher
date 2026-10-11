from __future__ import annotations

from quantpublisher.analysis.peer_comparison import (
    MIN_SAMPLE,
    GroupComparison,
    MetricComparison,
    PeerComparison,
    compute_peer_comparisons,
)
from quantpublisher.automation.peer_info import build_peer_groups, build_peer_inputs
from quantpublisher.database.models import CompanyProfile, Security
from quantpublisher.report import (
    MetricsBasis,
    PeerGroup,
    PeerMetricRow,
    StockMetrics,
    build_stock_report,
)
from quantpublisher.report.markdown import render_stock_report_markdown

BASIS = MetricsBasis(statement_year=2025, is_consolidated=1, valuation_month="2026-07")


def _group(key: str, size: int, value: float | None = 10.0) -> GroupComparison:
    metrics = tuple(
        MetricComparison(k, value, 5.0, 3, 20) for k in ("per", "pbr", "roe", "operating_margin")
    )
    return GroupComparison(key, size, metrics)


# ---- 변환 -------------------------------------------------------------------


def test_build_peer_inputs_pairs_each_metric_with_its_own_basis() -> None:
    securities = [Security("005930", "삼성전자", "KOSPI"), Security("000660", "Hynix", "KOSPI")]
    loaded = {
        "005930": (StockMetrics(per=10.0, pbr=1.0, roe=8.0, operating_margin=12.0), BASIS),
        "000660": (StockMetrics(), MetricsBasis()),
    }
    profiles = {"005930": CompanyProfile("005930", induty_code="26110")}

    inputs = {i.stock_code: i for i in build_peer_inputs(securities, loaded, profiles)}

    samsung = inputs["005930"]
    assert samsung.industry_code == "26110"
    assert samsung.values == {"per": 10.0, "pbr": 1.0, "roe": 8.0, "operating_margin": 12.0}
    assert samsung.bases == {
        "per": "2026-07",
        "pbr": "2026-07",
        "roe": "2025",
        "operating_margin": "2025",
    }
    assert inputs["000660"].industry_code is None
    assert inputs["000660"].bases["roe"] is None


def test_build_peer_groups_describes_industry_and_market() -> None:
    comparison = PeerComparison(industry=_group("264", 66), market=_group("KOSPI", 943))

    industry, market = build_peer_groups(comparison)

    assert industry is not None and market is not None
    assert industry.description == "전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업 중 KSIC 264 동종"
    assert industry.size == 66
    assert [row.label for row in industry.rows] == ["PER", "PBR", "ROE (%)", "영업이익률 (%)"]
    assert market.description == "KOSPI"


def test_build_peer_groups_two_digit_description_and_unknown_division() -> None:
    wide, _ = build_peer_groups(PeerComparison(_group("26", 100), _group("KOSPI", 5)))
    unknown, _ = build_peer_groups(PeerComparison(_group("99", 100), _group("KOSPI", 5)))

    assert wide is not None and wide.description.endswith("(KSIC 26)")
    assert unknown is not None and unknown.description == "KSIC 99"


def test_build_peer_groups_is_empty_without_comparison_or_values() -> None:
    assert build_peer_groups(None) == (None, None)
    assert build_peer_groups(PeerComparison(None, None)) == (None, None)
    no_values = PeerComparison(_group("264", 20, value=None), _group("KOSPI", 20, value=None))
    assert build_peer_groups(no_values) == (None, None)


def test_end_to_end_inputs_to_groups() -> None:
    securities = [Security(f"{i:06d}", f"종목{i}", "KOSPI") for i in range(1, 13)]
    loaded = {
        s.stock_code: (StockMetrics(roe=float(i), per=float(i), pbr=float(i)), BASIS)
        for i, s in enumerate(securities, start=1)
    }
    profiles = {s.stock_code: CompanyProfile(s.stock_code, induty_code="26110") for s in securities}

    comparisons = compute_peer_comparisons(build_peer_inputs(securities, loaded, profiles))
    industry, market = build_peer_groups(comparisons["000012"])

    assert industry is not None and market is not None
    roe = next(r for r in industry.rows if r.key == "roe")
    assert (roe.rank, roe.sample, roe.value) == (1, 12, 12.0)


# ---- 렌더링 -----------------------------------------------------------------


def _rows(rank: int | None = 3, sample: int = 20) -> tuple[PeerMetricRow, ...]:
    return tuple(
        PeerMetricRow(k, label, 10.0, 5.0, rank, sample)
        for k, label in (("per", "PER"), ("pbr", "PBR"), ("roe", "ROE (%)"), ("operating_margin", "영업이익률 (%)"))
    )


def _render(industry: PeerGroup | None, market: PeerGroup | None) -> str:
    report = build_stock_report(
        Security("005930", "Samsung", "KOSPI"),
        StockMetrics(),
        basis=BASIS,
        peer_industry=industry,
        peer_market=market,
    )
    return render_stock_report_markdown(report)


def test_markdown_renders_industry_and_market_table() -> None:
    markdown = _render(PeerGroup("반도체 업종", 66, _rows()), PeerGroup("KOSPI", 943, _rows(7, 614)))

    assert "## 동종 업종·시장 비교" in markdown
    assert "- 업종: 반도체 업종, 종목 66개" in markdown
    assert "- 시장: KOSPI, 종목 943개" in markdown
    assert "재무제표 2025년 연간, 연결, 밸류에이션 2026-07 월말" in markdown
    assert "| 지표 | 값 | 업종 중앙값 | 업종 내 순위 | 시장 중앙값 | 시장 내 순위 |" in markdown
    assert "| PER | 10.00 | 5.00 | 3위 / 20개 | 5.00 | 7위 / 614개 |" in markdown


def test_markdown_renders_market_only_table_with_reason() -> None:
    markdown = _render(None, PeerGroup("KOSDAQ", 1700, _rows(None, 8)))

    assert "- 업종: 비교할 수 있는 동종 종목이 %d개 미만이거나 업종 정보가 없어 생략했습니다." % MIN_SAMPLE in markdown
    assert "| 지표 | 값 | 시장 중앙값 | 시장 내 순위 |" in markdown
    assert "업종 내 순위" not in markdown
    assert "| ROE (%) | 10.00 | 5.00 | - |" in markdown  # 순위 없음은 '-'


def test_markdown_omits_peer_section_without_market_group() -> None:
    assert "동종 업종·시장 비교" not in _render(None, None)


def test_markdown_escapes_industry_description() -> None:
    markdown = _render(PeerGroup("제조업 {{< x >}} | 기타", 20, _rows()), PeerGroup("KOSPI", 20, _rows()))

    assert "{{<" not in markdown.split("## 동종 업종·시장 비교")[1]
