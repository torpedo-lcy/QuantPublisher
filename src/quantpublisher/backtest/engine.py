"""백테스트 실행 엔진.

가격 시계열과 매매 신호(0/1)를 입력받아 포트폴리오 가치 변화를
재현 가능하게 계산한다. 거래비용/슬리피지는 고려하지 않는다.

신호 해석:
    signals[i]는 i번째 거래일 종가까지의 데이터로 결정한 "목표 보유
    상태"를 의미한다. 실제 포지션은 그 다음 거래일(i+1)부터 반영된다
    (당일 종가로 신호를 계산한 뒤 다음 날 체결한다고 가정, look-ahead
    bias 방지).
"""

from __future__ import annotations

import logging

from quantpublisher.analysis.metrics import calculate_cumulative_return, calculate_max_drawdown
from quantpublisher.backtest.models import BacktestResult, EquityPoint, PricePoint, Trade

logger = logging.getLogger(__name__)


class BacktestInputError(ValueError):
    """백테스트 입력값이 유효하지 않을 때 발생한다."""


def run_backtest(
    prices: list[PricePoint],
    signals: list[int],
    initial_capital: float,
    strategy_name: str,
    stock_code: str,
) -> BacktestResult:
    """가격 시계열과 신호를 이용해 포트폴리오 결과를 계산한다.

    Args:
        prices: 오름차순으로 정렬된 가격 시계열 (최소 1개).
        signals: prices와 길이가 같은 0/1 신호 리스트.
        initial_capital: 초기 자본금 (0보다 커야 함).
        strategy_name: 결과에 기록할 전략 이름.
        stock_code: 대상 종목코드.

    Raises:
        BacktestInputError: 입력 길이가 다르거나, 비어 있거나,
            initial_capital이 0 이하인 경우.
    """
    if not prices:
        raise BacktestInputError("prices가 비어 있습니다.")
    if len(prices) != len(signals):
        raise BacktestInputError(
            f"prices와 signals의 길이가 다릅니다: "
            f"len(prices)={len(prices)}, len(signals)={len(signals)}"
        )
    if initial_capital <= 0:
        raise BacktestInputError(f"initial_capital은 0보다 커야 합니다: {initial_capital}")

    portfolio_value = initial_capital
    equity_curve = [EquityPoint(trade_date=prices[0].trade_date, portfolio_value=portfolio_value)]
    trades: list[Trade] = []
    held_position = 0

    for i in range(1, len(prices)):
        target_position = signals[i - 1]
        if target_position == 1:
            previous_close = prices[i - 1].close
            current_close = prices[i].close
            if previous_close > 0:
                daily_change = (current_close - previous_close) / previous_close
                portfolio_value = portfolio_value * (1 + daily_change)

        equity_curve.append(
            EquityPoint(trade_date=prices[i].trade_date, portfolio_value=portfolio_value)
        )

        if target_position != held_position:
            action = "BUY" if target_position == 1 else "SELL"
            trades.append(
                Trade(trade_date=prices[i].trade_date, action=action, price=prices[i].close)
            )
            held_position = target_position

    final_value = equity_curve[-1].portfolio_value
    total_return_pct = calculate_cumulative_return(initial_capital, final_value)
    max_drawdown_pct = calculate_max_drawdown(
        [point.portfolio_value for point in equity_curve]
    )

    logger.info(
        "backtest_completed strategy=%s stock_code=%s trades=%d final_value=%.2f",
        strategy_name,
        stock_code,
        len(trades),
        final_value,
    )

    return BacktestResult(
        strategy_name=strategy_name,
        stock_code=stock_code,
        initial_capital=initial_capital,
        final_value=final_value,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        trades=trades,
        equity_curve=equity_curve,
    )
