"""StockReport를 Jinja2 템플릿으로 Markdown 변환한다.

이 모듈은 지표를 계산하거나 StockReport를 만들지 않는다. 이미 만들어진
StockReport를 입력받아 Markdown 문자열 또는 파일로 변환하는 역할만
담당한다 (ARCHITECTURE.md 8절: 분석 결과 -> report model -> Jinja2
template -> Markdown).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from quantpublisher.analysis.performance import Change, ChangeKind, classify_change
from quantpublisher.report.models import FinancialYear, MetricsBasis, StockReport

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


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|~#])")
_MD_LIST_START = re.compile(r"^(\d+[.)]|[-+*])\s")


def _md_text(value: object) -> str:
    """외부(DART) 텍스트를 Markdown 본문/표 칸에 안전하게 넣을 수 있게 바꾼다.

    공백을 한 칸으로 줄이고, Markdown 특수문자를 이스케이프하며, Hugo가 shortcode로
    해석하는 `{{`를 깨뜨린다 (사업보고서 본문이 shortcode를 실행하지 못하게 한다).
    값이 None이면 빈 문자열이다.
    """
    if value is None:
        return ""
    text = " ".join(str(value).split())
    text = _MD_SPECIAL.sub(r"\\\1", text)
    text = text.replace("{{", "{&#8203;{").replace("}}", "}&#8203;}")
    if _MD_LIST_START.match(text):
        text = "\\" + text
    return text


def _md_code(value: object) -> str:
    """값을 인라인 코드로 감싼다 (링크로 해석되지 않는다). 빈 값이면 빈 문자열."""
    if value is None:
        return ""
    text = " ".join(str(value).replace("`", "").split())
    return f"`{text}`" if text else ""


_WON_PER_JO = 1_000_000_000_000  # 1조원
_WON_PER_EOK = 100_000_000  # 1억원


def _format_won(value: float | None) -> str:
    """원 단위 금액을 읽기 쉬운 문자열로 바꾼다 (예: "333.61조원", "-1,234억원").

    1조원 이상은 조원(소수 둘째 자리), 그 미만은 억원(정수), 1억원 미만은 원으로
    표시한다. None이면 "N/A"를 반환한다.
    """
    if value is None:
        return "N/A"
    if abs(value) >= _WON_PER_JO:
        return f"{value / _WON_PER_JO:,.2f}조원"
    if abs(value) >= _WON_PER_EOK:
        return f"{value / _WON_PER_EOK:,.0f}억원"
    return f"{value:,.0f}원"


def _comparison_text(change: Change | None, previous: float | None) -> str:
    """전기 대비 변화를 괄호 안에 넣을 문구로 바꾼다. 비교할 수 없으면 "전년 N/A"."""
    if change is None:
        return "전년 N/A"
    prev = _format_won(previous)
    kind = change.kind
    if kind in (ChangeKind.INCREASE, ChangeKind.DECREASE) and change.rate is not None:
        return f"전년 {prev} 대비 {change.rate:+.2f}%"
    labels = {
        ChangeKind.UNCHANGED: "전년과 동일",
        ChangeKind.TURNED_PROFIT: "흑자전환",
        ChangeKind.TURNED_LOSS: "적자전환",
        ChangeKind.LOSS_NARROWED: "적자 축소",
        ChangeKind.LOSS_WIDENED: "적자 확대",
    }
    return f"전년 {prev}, {labels.get(kind, '비교 불가')}"


def _is_comparable_year(latest: FinancialYear, previous: FinancialYear) -> bool:
    """직전 연도이고 연결/별도 기준이 충돌하지 않으면 True (없는 쪽은 충돌로 보지 않는다)."""
    if previous.year != latest.year - 1:
        return False
    if latest.is_consolidated is None or previous.is_consolidated is None:
        return True
    return latest.is_consolidated == previous.is_consolidated


def _performance_lines(report: StockReport) -> list[str]:
    """재무 시계열로 '주요 실적' 요약 문장(Markdown 목록 항목)을 만든다.

    가장 최근 연도를 직전 연도와 비교한다. 직전 연도가 없거나 연결/별도 기준이
    다르면 비교하지 않고 그 사실을 적는다. 시계열이 없으면 빈 목록이다.
    """
    history = report.financial_history
    if not history:
        return []
    latest = history[-1]
    consolidation = _consolidation_label(latest.is_consolidated)
    basis = f"{latest.year}년 연간" + (f", {consolidation}" if consolidation else "")
    lines = [f"- 기준: {basis}"]
    previous = history[-2] if len(history) >= 2 else None
    comparable = previous is not None and _is_comparable_year(latest, previous)
    if not comparable:
        lines.append(
            "- 전년 대비 증감: 비교할 수 없음 (직전 연도 데이터가 없거나 연결/별도 기준이 다름)"
        )
        previous = None

    for label, current, before in (
        ("매출액", latest.sales, previous.sales if previous else None),
        ("영업이익", latest.operating_income, previous.operating_income if previous else None),
        ("순이익", latest.net_income, previous.net_income if previous else None),
    ):
        if current is None:
            continue
        text = f"- {label}: {latest.year}년 {_format_won(current)}"
        if previous is not None:
            text += f" ({_comparison_text(classify_change(current, before), before)})"
        lines.append(text)

    for label, current_ratio, before_ratio in (
        ("영업이익률", latest.operating_margin, previous.operating_margin if previous else None),
        ("ROE", latest.roe, previous.roe if previous else None),
    ):
        if current_ratio is None:
            continue
        text = f"- {label}: {current_ratio:.2f}%"
        if before_ratio is not None:
            text += f" (전년 {before_ratio:.2f}%, {current_ratio - before_ratio:+.2f}%p)"
        lines.append(text)
    return lines


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
    env.filters["fmt_won"] = _format_won
    env.filters["md_text"] = _md_text
    env.filters["md_code"] = _md_code
    env.filters["consolidation_label"] = _consolidation_label
    env.globals["statement_basis"] = _statement_basis
    env.globals["growth_basis"] = _growth_basis
    env.globals["valuation_basis"] = _valuation_basis
    env.globals["performance_lines"] = _performance_lines
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
    output_dir가 존재하지 않으면 생성한다. 기존 파일의 내용이 렌더링 결과와
    같으면 다시 쓰지 않는다 (git 변경과 Hugo 재빌드를 최소화하기 위해).

    Args:
        report: 저장할 리포트 모델.
        output_dir: Markdown 파일을 저장할 디렉터리.

    Returns:
        Markdown 파일의 경로.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    content = render_stock_report_markdown(report)
    file_path = output_dir / f"{report.stock_code}.md"
    if file_path.exists() and file_path.read_text(encoding="utf-8") == content:
        logger.debug(
            "Markdown report unchanged: stock_code=%s path=%s",
            report.stock_code,
            file_path,
        )
        return file_path
    file_path.write_text(content, encoding="utf-8")
    logger.info(
        "Markdown report written: stock_code=%s path=%s",
        report.stock_code,
        file_path,
    )
    return file_path
