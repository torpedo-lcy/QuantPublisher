"""리포트 생성에 사용할 데이터 모델.

분석 결과를 웹 리포트(Markdown/Hugo)에서 사용할 구조로 정리한다.
이 모듈은 지표를 계산하지 않는다. 이미 계산된 값을 구조화하는
역할만 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StockMetrics:
    """리포트에 표시할 지표 값 모음.

    각 필드는 quantpublisher.analysis.metrics의 계산 함수 결과를
    그대로 담는다. 계산할 수 없었던 지표는 None으로 표현하며,
    표현 계층(Markdown/Hugo)은 None을 "N/A" 등으로 처리한다.
    """

    roe: float | None = None
    roa: float | None = None
    eps: float | None = None
    bps: float | None = None
    per: float | None = None
    pbr: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    debt_ratio: float | None = None
    dividend_yield: float | None = None
    revenue_growth_rate: float | None = None


@dataclass(frozen=True, slots=True)
class MetricsBasis:
    """지표 값의 기준 시점과 재무제표 기준(연결/별도) (Task 015).

    값만 보여주고 기준 시점을 숨기지 않기 위해 StockMetrics와 함께 리포트에
    전달한다. 기준 데이터가 없으면 해당 필드는 None이다.

    Attributes:
        statement_year: 재무제표 지표(ROE, ROA, 마진, 부채비율, 매출성장률)의
            기준 사업연도 (연간).
        is_consolidated: 1=연결, 0=별도, 모르면 None.
        valuation_month: 밸류에이션 지표(PER, PBR, EPS, BPS)의 기준 월 (YYYY-MM).
    """

    statement_year: int | None = None
    is_consolidated: int | None = None
    valuation_month: str | None = None


@dataclass(frozen=True, slots=True)
class FinancialYear:
    """연간 재무 시계열의 한 해 (Task 018).

    금액은 원 단위다. 계산할 수 없는 값은 None이며 표현 계층이 "N/A"로 표시한다.

    Attributes:
        year: 사업연도.
        is_consolidated: 1=연결, 0=별도, 모르면 None. 해마다 달라질 수 있다.
        sales: 매출액.
        operating_income: 영업이익.
        net_income: 당기순이익.
        operating_margin: 영업이익률(%).
        roe: 자기자본이익률(%).
    """

    year: int
    is_consolidated: int | None = None
    sales: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    operating_margin: float | None = None
    roe: float | None = None


@dataclass(frozen=True, slots=True)
class CompanyInfo:
    """종목 페이지의 '기업 개요' 섹션에 표시할 값 (Task 019). 값이 없으면 None/빈 튜플.

    Attributes:
        industry_code: KSIC 업종코드 (DART).
        industry_name: 업종코드의 중분류 이름. 모르는 코드면 None.
        established_date: 설립일 (YYYY-MM-DD).
        ceo_name: 대표자명.
        address: 본점 소재지.
        homepage: 홈페이지 주소 (원천 그대로).
        fiscal_month: 결산월 (1~12).
        business_summary: 사업보고서 '사업의 개요' 발췌.
        history: 연혁 (연도, 내용) 목록. 최신 연도가 먼저 온다.
        report_year: 사업 요약과 연혁을 가져온 사업보고서의 사업연도.
    """

    industry_code: str | None = None
    industry_name: str | None = None
    established_date: str | None = None
    ceo_name: str | None = None
    address: str | None = None
    homepage: str | None = None
    fiscal_month: int | None = None
    business_summary: str | None = None
    history: tuple[tuple[int, str], ...] = ()
    report_year: int | None = None


@dataclass(frozen=True, slots=True)
class PeerMetricRow:
    """동종 비교 표의 한 지표 (Task 020).

    Attributes:
        key: 지표 키 (per, pbr, roe, operating_margin).
        label: 표에 쓸 이름 (예: "ROE (%)").
        value: 이 종목의 값. 없으면 None.
        median: 비교 그룹의 중앙값. 표본이 부족하면 None.
        rank: 값이 큰 순서의 순위(1이 최대). 비교 대상이 아니거나 표본이 부족하면 None.
        sample: 비교에 쓰인 종목 수.
    """

    key: str
    label: str
    value: float | None = None
    median: float | None = None
    rank: int | None = None
    sample: int = 0


@dataclass(frozen=True, slots=True)
class PeerGroup:
    """비교 그룹(업종 또는 시장) 하나.

    Attributes:
        description: 그룹 설명 (예: "전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업 (KSIC 261)", "KOSPI").
        size: 그룹에 속한 종목 수.
        rows: 지표별 비교.
    """

    description: str
    size: int
    rows: tuple[PeerMetricRow, ...] = ()


@dataclass(frozen=True, slots=True)
class StockReport:
    """종목 하나에 대한 리포트 모델.

    Markdown/Hugo 등 표현 계층은 이 구조체만 참조하면 되고, DB나
    지표 계산 로직에 직접 접근하지 않는다.

    Attributes:
        stock_code: 종목코드.
        name: 종목명.
        market: 시장 구분.
        metrics: 계산된 지표 모음.
        data_date: 데이터 기준일 (해당 종목의 최신 거래일, YYYY-MM-DD). 실행 시각이
            아니라 데이터에서 정해지므로 데이터가 같으면 렌더링 결과도 같다.
            가격 데이터가 없으면 None.
        basis: 지표의 기준 연도/월과 연결/별도 구분. 지정하지 않으면 모두 None.
        has_price_chart: 가격 차트 JSON이 생성되어 페이지에 차트를 넣을 수 있는지 여부.
        financial_history: 연간 재무 시계열 (연도 오름차순). 없으면 빈 튜플.
        has_financial_chart: 재무 차트 JSON이 생성되어 차트를 넣을 수 있는지 여부.
        company: 기업 개요. 수집되지 않았으면 None.
        peer_industry: 동종 업종 비교. 업종 그룹을 만들 수 없으면 None.
        peer_market: 같은 시장 비교. 비교할 값이 없으면 None.
    """

    stock_code: str
    name: str
    market: str
    metrics: StockMetrics
    data_date: str | None = None
    basis: MetricsBasis = MetricsBasis()
    has_price_chart: bool = False
    financial_history: tuple[FinancialYear, ...] = ()
    has_financial_chart: bool = False
    company: CompanyInfo | None = None
    peer_industry: PeerGroup | None = None
    peer_market: PeerGroup | None = None
