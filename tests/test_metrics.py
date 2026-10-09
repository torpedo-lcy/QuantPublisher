from __future__ import annotations

import math

from quantpublisher.analysis.metrics import (
    calculate_bps,
    calculate_cumulative_return,
    calculate_daily_return,
    calculate_debt_ratio,
    calculate_dividend_yield,
    calculate_eps,
    calculate_max_drawdown,
    calculate_net_margin,
    calculate_operating_margin,
    calculate_pbr,
    calculate_per,
    calculate_revenue_growth_rate,
    calculate_roa,
    calculate_roe,
)


def test_calculate_roe_returns_expected_value() -> None:
    assert calculate_roe(net_income=1000, equity=10000) == 10.0


def test_calculate_roe_returns_none_when_equity_is_zero() -> None:
    assert calculate_roe(net_income=1000, equity=0) is None


def test_calculate_roe_returns_none_when_net_income_is_missing() -> None:
    assert calculate_roe(net_income=None, equity=10000) is None


def test_calculate_roe_returns_none_when_equity_is_missing() -> None:
    assert calculate_roe(net_income=1000, equity=None) is None


def test_calculate_roe_handles_negative_net_income() -> None:
    assert calculate_roe(net_income=-500, equity=10000) == -5.0


def test_calculate_roa_returns_expected_value() -> None:
    assert calculate_roa(net_income=1000, total_assets=20000) == 5.0


def test_calculate_roa_returns_none_when_total_assets_is_zero() -> None:
    assert calculate_roa(net_income=1000, total_assets=0) is None


def test_calculate_eps_returns_expected_value() -> None:
    assert calculate_eps(net_income=1_000_000, shares_outstanding=1000) == 1000.0


def test_calculate_eps_returns_none_when_shares_outstanding_is_zero() -> None:
    assert calculate_eps(net_income=1_000_000, shares_outstanding=0) is None


def test_calculate_bps_returns_expected_value() -> None:
    assert calculate_bps(equity=1_000_000, shares_outstanding=1000) == 1000.0


def test_calculate_bps_returns_none_when_shares_outstanding_is_zero() -> None:
    assert calculate_bps(equity=1_000_000, shares_outstanding=0) is None


def test_calculate_per_returns_expected_value() -> None:
    assert calculate_per(price=10000, eps=1000) == 10.0


def test_calculate_per_returns_none_when_eps_is_zero() -> None:
    assert calculate_per(price=10000, eps=0) is None


def test_calculate_per_returns_none_when_eps_is_missing() -> None:
    assert calculate_per(price=10000, eps=None) is None


def test_calculate_pbr_returns_expected_value() -> None:
    assert calculate_pbr(price=5000, bps=2500) == 2.0


def test_calculate_pbr_returns_none_when_bps_is_zero() -> None:
    assert calculate_pbr(price=5000, bps=0) is None


def test_calculate_operating_margin_returns_expected_value() -> None:
    assert calculate_operating_margin(operating_income=200, revenue=1000) == 20.0


def test_calculate_operating_margin_returns_none_when_revenue_is_zero() -> None:
    assert calculate_operating_margin(operating_income=200, revenue=0) is None


def test_calculate_net_margin_returns_expected_value() -> None:
    assert calculate_net_margin(net_income=100, revenue=1000) == 10.0


def test_calculate_net_margin_returns_none_when_revenue_is_missing() -> None:
    assert calculate_net_margin(net_income=100, revenue=None) is None


def test_calculate_debt_ratio_returns_expected_value() -> None:
    assert calculate_debt_ratio(total_liabilities=4000, equity=2000) == 200.0


def test_calculate_debt_ratio_returns_none_when_equity_is_zero() -> None:
    assert calculate_debt_ratio(total_liabilities=4000, equity=0) is None


def test_calculate_dividend_yield_returns_expected_value() -> None:
    assert calculate_dividend_yield(dividend_per_share=500, price=10000) == 5.0


def test_calculate_dividend_yield_returns_none_when_price_is_zero() -> None:
    assert calculate_dividend_yield(dividend_per_share=500, price=0) is None


def test_calculate_revenue_growth_rate_returns_expected_value() -> None:
    result = calculate_revenue_growth_rate(current_revenue=1200, previous_revenue=1000)
    assert result is not None
    assert math.isclose(result, 20.0)


def test_calculate_revenue_growth_rate_returns_none_when_previous_revenue_is_zero() -> None:
    assert calculate_revenue_growth_rate(current_revenue=1200, previous_revenue=0) is None


def test_calculate_revenue_growth_rate_returns_none_when_current_revenue_is_missing() -> None:
    assert calculate_revenue_growth_rate(current_revenue=None, previous_revenue=1000) is None


def test_calculate_revenue_growth_rate_handles_negative_growth() -> None:
    result = calculate_revenue_growth_rate(current_revenue=800, previous_revenue=1000)
    assert result is not None
    assert math.isclose(result, -20.0)


def test_calculate_daily_return_returns_expected_value() -> None:
    result = calculate_daily_return(previous_close=100, current_close=105)
    assert result is not None
    assert math.isclose(result, 5.0)


def test_calculate_daily_return_returns_none_when_previous_close_is_zero() -> None:
    assert calculate_daily_return(previous_close=0, current_close=105) is None


def test_calculate_daily_return_returns_none_when_current_close_is_missing() -> None:
    assert calculate_daily_return(previous_close=100, current_close=None) is None


def test_calculate_cumulative_return_returns_expected_value() -> None:
    result = calculate_cumulative_return(initial_value=1_000_000, final_value=1_125_000)
    assert result is not None
    assert math.isclose(result, 12.5)


def test_calculate_cumulative_return_returns_none_when_initial_value_is_zero() -> None:
    assert calculate_cumulative_return(initial_value=0, final_value=1000) is None


def test_calculate_max_drawdown_returns_expected_value() -> None:
    result = calculate_max_drawdown([100, 110, 90, 95, 120])
    assert result is not None
    assert math.isclose(result, (90 - 110) / 110 * 100)


def test_calculate_max_drawdown_returns_zero_for_monotonic_increase() -> None:
    result = calculate_max_drawdown([100, 105, 110])
    assert result is not None
    assert math.isclose(result, 0.0)


def test_calculate_max_drawdown_returns_none_for_empty_list() -> None:
    assert calculate_max_drawdown([]) is None


def test_calculate_max_drawdown_returns_none_when_value_is_not_positive() -> None:
    assert calculate_max_drawdown([100, 0, 90]) is None
