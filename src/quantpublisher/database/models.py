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
        created_at: 최초 등록 시각 (ISO 8601 문자열, DB에서 자동 설정).
        updated_at: 마지막 수정 시각 (ISO 8601 문자열, DB에서 자동 설정).
    """

    stock_code: str
    name: str
    market: str
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None
