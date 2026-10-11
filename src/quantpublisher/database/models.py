"""데이터베이스 도메인 모델.

Repository가 다루는 데이터 구조를 정의한다.
분석 의미나 계산 로직은 포함하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Security:
    """종목 정보.

    Attributes:
        stock_code: 종목코드 (예: "005930"). Primary key.
        name: 종목명.
        market: 시장 구분 (예: "KOSPI", "KOSDAQ").
        is_active: 현재 거래 가능 여부.
        corp_code: DART 고유번호 8자리. 아직 모르면 None.
        created_at: 최초 등록 시각 (ISO 8601 문자열, DB에서 자동 설정).
        updated_at: 마지막 수정 시각 (ISO 8601 문자열, DB에서 자동 설정).
    """

    stock_code: str
    name: str
    market: str
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None
    corp_code: str | None = None


@dataclass(frozen=True, slots=True)
class PriceDaily:
    """일봉 가격 한 행.

    Attributes:
        stock_code: 종목코드. securities.stock_code를 참조한다.
        trade_date: 거래일 (YYYY-MM-DD).
        open: 시가.
        high: 고가.
        low: 저가.
        close: 종가.
        volume: 거래량.
    """

    stock_code: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class FinancialStatement:
    """연간 재무제표 한 행 (금액 단위는 원천 quant.db와 같은 원).

    값이 없거나 미공시면 None이다. 특히 net_income은 원천에서 0.0이면 "미공시"로
    보고 None으로 저장한다 (Task 014).

    Attributes:
        stock_code: 종목코드. securities.stock_code를 참조한다.
        year: 사업연도 (예: 2025).
        report_type: DART 보고서 구분. 이 프로젝트에서는 "11011"(연간)만 저장한다.
        is_consolidated: 1=연결, 0=별도, 모르면 None.
    """

    stock_code: str
    year: int
    report_type: str
    assets: float | None = None
    liabilities: float | None = None
    equity: float | None = None
    current_assets: float | None = None
    current_liab: float | None = None
    sales: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    is_consolidated: int | None = None


@dataclass(frozen=True, slots=True)
class FinancialMetric:
    """월별 밸류에이션 한 행.

    Attributes:
        stock_code: 종목코드. securities.stock_code를 참조한다.
        year_month: 기준 월 (YYYY-MM, 월말 기준).
        trade_date: 그 달의 마지막 거래일 (YYYY-MM-DD). 없으면 None.
        close_price: 종가.
        market_cap: 시가총액 (원).
        shares_out: 상장주식수.
        per, pbr, psr, pcr: 원천 값을 그대로 저장한다 (재계산/보정하지 않는다).
    """

    stock_code: str
    year_month: str
    trade_date: str | None = None
    close_price: float | None = None
    market_cap: float | None = None
    shares_out: float | None = None
    per: float | None = None
    pbr: float | None = None
    psr: float | None = None
    pcr: float | None = None


@dataclass(frozen=True, slots=True)
class CompanyProfile:
    """기업 개요 한 행 (Task 019). 값이 없으면 None이다.

    Attributes:
        stock_code: 종목코드. securities.stock_code를 참조한다.
        induty_code: KSIC 업종코드 (DART company.json의 induty_code).
        established_date: 설립일 (YYYY-MM-DD).
        ceo_name: 대표자명.
        address: 본점 소재지.
        homepage: 홈페이지 주소 (원천 그대로, 스킴이 없을 수 있다).
        fiscal_month: 결산월 (1~12).
        business_summary: 사업보고서 '사업의 개요'에서 발췌한 요약.
        history_json: 연혁을 [[연도, 내용], ...] 형태로 담은 JSON 문자열.
        report_rcept_no: 본문을 가져온 사업보고서 접수번호.
        report_year: 그 사업보고서의 사업연도.
    """

    stock_code: str
    induty_code: str | None = None
    established_date: str | None = None
    ceo_name: str | None = None
    address: str | None = None
    homepage: str | None = None
    fiscal_month: int | None = None
    business_summary: str | None = None
    history_json: str | None = None
    report_rcept_no: str | None = None
    report_year: int | None = None
