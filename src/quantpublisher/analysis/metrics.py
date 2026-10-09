"""기본 투자 지표 계산 함수.

이 모듈의 함수는 순수 함수로 작성한다. DB나 외부 API를 직접 읽지 않고,
호출자가 전달한 값만으로 지표를 계산한다.

결측값(None)이나 0으로 나누는 상황에서는 예외를 발생시키지 않고
None을 반환한다. 호출자는 반환값이 None인 경우 지표를 계산할 수
없었다는 의미로 해석한다.
"""

from __future__ import annotations


def _safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    """numerator / denominator를 안전하게 계산한다.

    numerator 또는 denominator가 None이거나 denominator가 0이면 None을
    반환한다.
    """
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return numerator / denominator


def calculate_roe(net_income: float | None, equity: float | None) -> float | None:
    """자기자본이익률(ROE, %)을 계산한다.

    ROE = 당기순이익 / 자기자본 * 100

    equity가 0이거나 결측이면 None을 반환한다.
    """
    ratio = _safe_divide(net_income, equity)
    return ratio * 100 if ratio is not None else None


def calculate_roa(net_income: float | None, total_assets: float | None) -> float | None:
    """총자산이익률(ROA, %)을 계산한다.

    ROA = 당기순이익 / 총자산 * 100

    total_assets가 0이거나 결측이면 None을 반환한다.
    """
    ratio = _safe_divide(net_income, total_assets)
    return ratio * 100 if ratio is not None else None


def calculate_eps(net_income: float | None, shares_outstanding: float | None) -> float | None:
    """주당순이익(EPS)을 계산한다.

    EPS = 당기순이익 / 발행주식수

    shares_outstanding이 0이거나 결측이면 None을 반환한다.
    """
    return _safe_divide(net_income, shares_outstanding)


def calculate_bps(equity: float | None, shares_outstanding: float | None) -> float | None:
    """주당순자산(BPS)을 계산한다.

    BPS = 자기자본 / 발행주식수

    shares_outstanding이 0이거나 결측이면 None을 반환한다.
    """
    return _safe_divide(equity, shares_outstanding)


def calculate_per(price: float | None, eps: float | None) -> float | None:
    """주가수익비율(PER)을 계산한다.

    PER = 주가 / EPS

    EPS가 0(적자로 인한 무의미한 배수 포함)이거나 결측이면 None을
    반환한다.
    """
    return _safe_divide(price, eps)


def calculate_pbr(price: float | None, bps: float | None) -> float | None:
    """주가순자산비율(PBR)을 계산한다.

    PBR = 주가 / BPS

    BPS가 0이거나 결측이면 None을 반환한다.
    """
    return _safe_divide(price, bps)


def calculate_operating_margin(
    operating_income: float | None, revenue: float | None
) -> float | None:
    """영업이익률(%)을 계산한다.

    영업이익률 = 영업이익 / 매출액 * 100

    revenue가 0이거나 결측이면 None을 반환한다.
    """
    ratio = _safe_divide(operating_income, revenue)
    return ratio * 100 if ratio is not None else None


def calculate_net_margin(net_income: float | None, revenue: float | None) -> float | None:
    """순이익률(%)을 계산한다.

    순이익률 = 당기순이익 / 매출액 * 100

    revenue가 0이거나 결측이면 None을 반환한다.
    """
    ratio = _safe_divide(net_income, revenue)
    return ratio * 100 if ratio is not None else None


def calculate_debt_ratio(
    total_liabilities: float | None, equity: float | None
) -> float | None:
    """부채비율(%)을 계산한다.

    부채비율 = 총부채 / 자기자본 * 100

    equity가 0이거나 결측이면 None을 반환한다.
    """
    ratio = _safe_divide(total_liabilities, equity)
    return ratio * 100 if ratio is not None else None


def calculate_dividend_yield(
    dividend_per_share: float | None, price: float | None
) -> float | None:
    """배당수익률(%)을 계산한다.

    배당수익률 = 주당배당금 / 주가 * 100

    price가 0이거나 결측이면 None을 반환한다.
    """
    ratio = _safe_divide(dividend_per_share, price)
    return ratio * 100 if ratio is not None else None


def calculate_revenue_growth_rate(
    current_revenue: float | None, previous_revenue: float | None
) -> float | None:
    """매출액 증가율(%)을 계산한다.

    증가율 = (당기매출 - 전기매출) / 전기매출 * 100

    previous_revenue가 0이거나 결측이면 None을 반환한다.
    당기 값이 결측이면 None을 반환한다.
    """
    if current_revenue is None or previous_revenue is None:
        return None
    growth = _safe_divide(current_revenue - previous_revenue, previous_revenue)
    return growth * 100 if growth is not None else None


def calculate_daily_return(
    previous_close: float | None, current_close: float | None
) -> float | None:
    """전일 종가 대비 당일 수익률(%)을 계산한다.

    수익률 = (당일 종가 - 전일 종가) / 전일 종가 * 100

    previous_close가 0이거나 결측이면 None을 반환한다.
    """
    if current_close is None or previous_close is None:
        return None
    ratio = _safe_divide(current_close - previous_close, previous_close)
    return ratio * 100 if ratio is not None else None


def calculate_cumulative_return(
    initial_value: float | None, final_value: float | None
) -> float | None:
    """초기값 대비 최종값의 누적 수익률(%)을 계산한다.

    누적 수익률 = (최종값 - 초기값) / 초기값 * 100

    initial_value가 0이거나 결측이면 None을 반환한다.
    """
    if final_value is None or initial_value is None:
        return None
    ratio = _safe_divide(final_value - initial_value, initial_value)
    return ratio * 100 if ratio is not None else None


def calculate_max_drawdown(values: list[float]) -> float | None:
    """시계열의 최대 낙폭(MDD, %)을 계산한다.

    각 시점까지의 최고점 대비 하락폭 중 가장 큰 값을 음수(%)로 반환한다.
    (예: 고점 대비 20% 하락하면 -20.0)

    values가 비어 있으면 None을 반환한다.
    values에 0 이하의 값이 포함되면 낙폭을 의미 있게 계산할 수 없으므로
    None을 반환한다.
    """
    if not values:
        return None
    if any(value <= 0 for value in values):
        return None

    peak = values[0]
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = (value - peak) / peak * 100
        max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown
