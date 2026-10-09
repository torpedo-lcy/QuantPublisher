"""백테스트 모듈(strategy/engine) 테스트.

- 전략 신호 계산: 손으로 검증 가능한 짧은 가격 시계열로 확인.
- 엔진 포트폴리오 계산: 직접 구성한 신호로 자본 변화를 검증.
- fixture 기반 통합 테스트: 가격 fixture로 실행한 결과가 재현 가능한지
  (몇 번을 실행해도 동일한 결과가 나오는지) 확인.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from quantpublisher.backtest.engine import BacktestInputError, run_backtest
from quantpublisher.backtest.models import PricePoint
from quantpublisher.backtest.strategy import (
    InvalidStrategyParameterError,
    moving_average_crossover_signals,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_price_fixture(name: str) -> list[PricePoint]:
    with (FIXTURES_DIR / name).open("r", encoding="utf-8") as f:
        raw_rows = json.load(f)
    return [PricePoint(trade_date=row["trade_date"], close=row["close"]) for row in raw_rows]


# ── moving_average_crossover_signals ────────────────────────────────────


def test_moving_average_crossover_signals_returns_zero_before_long_window_is_filled() -> None:
    prices = [
        PricePoint("2024-01-01", 100),
        PricePoint("2024-01-02", 101),
        PricePoint("2024-01-03", 102),
    ]
    signals = moving_average_crossover_signals(prices, short_window=2, long_window=4)
    assert signals == [0, 0, 0]


def test_moving_average_crossover_signals_detects_upward_crossover() -> None:
    # SMA2 vs SMA4: 4번째 데이터부터 이동평균 계산 가능.
    # closes: 100, 98, 95, 90, 92, 96 → SMA2[5]=94, SMA4[5]=93.25 → 상향 돌파
    prices = [
        PricePoint("2024-01-01", 100),
        PricePoint("2024-01-02", 98),
        PricePoint("2024-01-03", 95),
        PricePoint("2024-01-04", 90),
        PricePoint("2024-01-05", 92),
        PricePoint("2024-01-08", 96),
    ]
    signals = moving_average_crossover_signals(prices, short_window=2, long_window=4)
    assert signals == [0, 0, 0, 0, 0, 1]


def test_moving_average_crossover_signals_raises_when_short_window_not_less_than_long() -> None:
    prices = [PricePoint("2024-01-01", 100)]
    with pytest.raises(InvalidStrategyParameterError):
        moving_average_crossover_signals(prices, short_window=4, long_window=4)


def test_moving_average_crossover_signals_raises_when_window_is_not_positive() -> None:
    prices = [PricePoint("2024-01-01", 100)]
    with pytest.raises(InvalidStrategyParameterError):
        moving_average_crossover_signals(prices, short_window=0, long_window=2)


# ── run_backtest ─────────────────────────────────────────────────────────


def test_run_backtest_holds_cash_value_when_never_invested() -> None:
    prices = [
        PricePoint("2024-01-01", 100),
        PricePoint("2024-01-02", 110),
        PricePoint("2024-01-03", 90),
    ]
    signals = [0, 0, 0]
    result = run_backtest(
        prices, signals, initial_capital=1_000_000, strategy_name="test", stock_code="000000"
    )
    assert result.final_value == 1_000_000
    assert result.total_return_pct == 0.0
    assert result.trades == []
    assert len(result.equity_curve) == 3


def test_run_backtest_applies_price_change_only_after_signal_day() -> None:
    prices = [
        PricePoint("2024-01-01", 100),
        PricePoint("2024-01-02", 110),  # 신호는 아직 0이므로 반영 안 됨
        PricePoint("2024-01-03", 121),  # 전날 신호가 1이므로 10% 상승 반영
    ]
    signals = [0, 1, 1]
    result = run_backtest(
        prices, signals, initial_capital=1_000_000, strategy_name="test", stock_code="000000"
    )
    assert result.equity_curve[1].portfolio_value == 1_000_000
    assert math.isclose(result.equity_curve[2].portfolio_value, 1_100_000.0)
    assert result.final_value == result.equity_curve[-1].portfolio_value
    assert len(result.trades) == 1
    assert result.trades[0].action == "BUY"
    assert result.trades[0].trade_date == "2024-01-03"


def test_run_backtest_records_buy_and_sell_trades_on_signal_change() -> None:
    prices = [
        PricePoint("2024-01-01", 100),
        PricePoint("2024-01-02", 105),
        PricePoint("2024-01-03", 110),
        PricePoint("2024-01-04", 108),
    ]
    signals = [1, 1, 0, 0]
    result = run_backtest(
        prices, signals, initial_capital=1_000_000, strategy_name="test", stock_code="000000"
    )
    actions = [(t.trade_date, t.action) for t in result.trades]
    assert actions == [("2024-01-02", "BUY"), ("2024-01-04", "SELL")]


def test_run_backtest_raises_when_lengths_mismatch() -> None:
    prices = [PricePoint("2024-01-01", 100), PricePoint("2024-01-02", 101)]
    with pytest.raises(BacktestInputError):
        run_backtest(
            prices, [0], initial_capital=1_000_000, strategy_name="test", stock_code="000000"
        )


def test_run_backtest_raises_when_prices_is_empty() -> None:
    with pytest.raises(BacktestInputError):
        run_backtest(
            [], [], initial_capital=1_000_000, strategy_name="test", stock_code="000000"
        )


def test_run_backtest_raises_when_initial_capital_is_not_positive() -> None:
    prices = [PricePoint("2024-01-01", 100)]
    with pytest.raises(BacktestInputError):
        run_backtest(
            prices, [0], initial_capital=0, strategy_name="test", stock_code="000000"
        )


# ── fixture 기반 통합 테스트: 재현 가능성 ──────────────────────────────────


def test_backtest_result_is_reproducible_from_fixture() -> None:
    prices = _load_price_fixture("backtest_prices_sample.json")

    def _run() -> tuple[float, float | None, list[tuple[str, str, float]]]:
        signals = moving_average_crossover_signals(prices, short_window=2, long_window=4)
        result = run_backtest(
            prices,
            signals,
            initial_capital=1_000_000,
            strategy_name="sma_crossover",
            stock_code="005930",
        )
        trade_tuples = [(t.trade_date, t.action, t.price) for t in result.trades]
        return result.final_value, result.total_return_pct, trade_tuples

    first_run = _run()
    second_run = _run()
    assert first_run == second_run


def test_backtest_result_matches_expected_values_from_fixture() -> None:
    prices = _load_price_fixture("backtest_prices_sample.json")
    signals = moving_average_crossover_signals(prices, short_window=2, long_window=4)

    result = run_backtest(
        prices,
        signals,
        initial_capital=1_000_000,
        strategy_name="sma_crossover",
        stock_code="005930",
    )

    assert len(result.equity_curve) == len(prices)
    assert result.equity_curve[0].portfolio_value == 1_000_000
    assert result.final_value == result.equity_curve[-1].portfolio_value

    assert math.isclose(result.final_value, 1_125_000.0, rel_tol=1e-6)
    assert result.total_return_pct is not None
    assert math.isclose(result.total_return_pct, 12.5, rel_tol=1e-6)
    assert result.max_drawdown_pct is not None
    assert math.isclose(result.max_drawdown_pct, -1.9047619, rel_tol=1e-5)

    assert len(result.trades) == 1
    assert result.trades[0].action == "BUY"
    assert result.trades[0].trade_date == "2024-01-10"
