"""백테스트 도메인 모델.

이 모듈은 계산 로직을 포함하지 않는다. 백테스트 입력(가격 시계열)과
결과(포트폴리오 가치, 거래 내역)를 표현하는 구조만 정의한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PricePoint:
    """단일 거래일의 종가.

    Attributes:
        trade_date: 거래일 (YYYY-MM-DD 문자열). 오름차순으로 정렬되어
            있다고 가정한다.
        close: 종가. 0보다 커야 한다.
    """

    trade_date: str
    close: float


@dataclass(frozen=True, slots=True)
class Trade:
    """전략 신호 변화에 따라 발생한 매매 기록.

    Attributes:
        trade_date: 매매가 체결된 날짜.
        action: "BUY" 또는 "SELL".
        price: 체결 가격 (해당 날짜의 종가).
    """

    trade_date: str
    action: str
    price: float


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """특정 시점의 포트폴리오 평가금액.

    Attributes:
        trade_date: 평가 기준일.
        portfolio_value: 해당 시점의 포트폴리오 평가금액.
    """

    trade_date: str
    portfolio_value: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """백테스트 실행 결과.

    Attributes:
        strategy_name: 실행한 전략의 이름.
        stock_code: 대상 종목코드.
        initial_capital: 초기 자본금.
        final_value: 마지막 시점의 포트폴리오 평가금액.
        total_return_pct: 누적 수익률(%). 계산 불가 시 None.
        max_drawdown_pct: 최대 낙폭(%, 0 이하 값). 계산 불가 시 None.
        trades: 발생한 매매 기록 (시간 순).
        equity_curve: 시점별 포트폴리오 평가금액.
    """

    strategy_name: str
    stock_code: str
    initial_capital: float
    final_value: float
    total_return_pct: float | None
    max_drawdown_pct: float | None
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
