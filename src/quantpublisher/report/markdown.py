"""StockReport를 Jinja2 템플릿으로 Markdown 변환한다.

이 모듈은 지표를 계산하거나 StockReport를 만들지 않는다. 이미 만들어진
StockReport를 입력받아 Markdown 문자열 또는 파일로 변환하는 역할만
담당한다 (ARCHITECTURE.md 8절: 분석 결과 -> report model -> Jinja2
template -> Markdown).
"""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from quantpublisher.report.models import MetricsBasis, StockReport

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_TEMPLATE_NAME = "stock_report.md.j2"


def _format_metric(value: float | None) -> str:
    """지표 값을 Markdown 표시용 문자열로 변환한다.

    None이면 "N/A"를 반환한다. 값이 있으면 소수점 둘째 자리까지
    반올림한 문자열을 반환한다.
    """
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def _consolidation_label(is_consolidated: int | None) -> str:
    """is_consolidated 값을 "연결"/"별도" 표시로 변환한다. 모르면 빈 문자열."""
    if is_consolidated == 1:
        return "연결"
    if is_consolidated == 0:
        return "별도"
    return ""


def _statement_basis(basis: MetricsBasis) -> str:
    """재무제표 기준 표시 문자열 (예: "2025년 연간, 연결"). 없으면 "N/A"."""
    if basis.statement_year is None:
        return "N/A"
    label = f"{basis.statement_year}년 연간"
    consolidation = _consolidation_label(basis.is_consolidated)
    return f"{label}, {consolidation}" if consolidation else label


def _growth_basis(basis: MetricsBasis) -> str:
    """매출성장률 기준 표시 문자열 (예: "2024→2025년 연간, 연결")."""
    if basis.statement_year is None:
        return "N/A"
    year = basis.statement_year
    label = f"{year - 1}→{year}년 연간"
    consolidation = _consolidation_label(basis.is_consolidated)
    return f"{label}, {consolidation}" if consolidation else label


def _valuation_basis(basis: MetricsBasis) -> str:
    """밸류에이션 기준 표시 문자열 (예: "2026-09 월말"). 없으면 "N/A"."""
    if basis.valuation_month is None:
        return "N/A"
    return f"{basis.valuation_month} 월말"


def _basis_cell(value: float | None, basis_label: str, note: str = "") -> str:
    """지표 표의 '기준' 칸. 값이 N/A면 기준도 "-"로 표시한다.

    note가 있으면 기준 뒤에 덧붙인다 (예: "2026-09 월말, 종가/PER").
    """
    if value is None or basis_label == "N/A":
        return "-"
    return f"{basis_label}, {note}" if note else basis_label


def _build_environment() -> Environment:
    """Markdown 렌더링에 사용할 Jinja2 Environment를 생성한다."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["fmt_metric"] = _format_metric
    env.filters["basis_cell"] = _basis_cell
    env.globals["statement_basis"] = _statement_basis
    env.globals["growth_basis"] = _growth_basis
    env.globals["valuation_basis"] = _valuation_basis
    return env


_ENV = _build_environment()


def render_stock_report_markdown(report: StockReport) -> str:
    """StockReport를 Markdown 문자열로 렌더링한다.

    front matter(title, stock_code, market, date)와 주요 지표 표를
    포함한다. 지표마다 기준 연도/월(연결/별도 포함)을 함께 표시한다.
    """
    template = _ENV.get_template(_TEMPLATE_NAME)
    return template.render(report=report)


def write_stock_report_markdown(report: StockReport, output_dir: Path) -> Path:
    """StockReport를 Markdown 파일로 저장한다.

    파일명은 종목코드를 기준으로 한다 (예: 005930.md).
    output_dir가 존재하지 않으면 생성한다.

    Args:
        report: 저장할 리포트 모델.
        output_dir: Markdown 파일을 저장할 디렉터리.

    Returns:
        생성된 Markdown 파일의 경로.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    content = render_stock_report_markdown(report)
    file_path = output_dir / f"{report.stock_code}.md"
    file_path.write_text(content, encoding="utf-8")
    logger.info(
        "Markdown report written: stock_code=%s path=%s",
        report.stock_code,
        file_path,
    )
    return file_path
