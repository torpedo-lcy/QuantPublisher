"""단일 전략: 단순이동평균(SMA) 교차 전략.

이 모듈의 함수는 순수 함수로 작성한다. DB나 외부 API를 직접 읽지 않고,
호출자가 전달한 가격 시계열만으로 매매 신호를 계산한다.

전략 규칙:
    단기 이동평균이 장기 이동평균보다 높으면 보유(1), 아니면 미보유(0).
    이동평균을 계산할 만큼 데이터가 쌓이기 전에는 미보유(0)로 처리한다.

신호는 오직 해당 시점까지의 데이터로만 계산되므로 미래 데이터를
참조하지 않는다 (look-ahead bias 없음).
"""

from __future__ import annotations

from quantpublisher.backtest.models import PricePoint

STRATEGY_NAME = "sma_crossover"


class InvalidStrategyParameterError(ValueError):
    """전략 파라미터가 유효하지 않을 때 발생한다."""


def moving_average_crossover_signals(
    prices: list[PricePoint],
    short_window: int,
    long_window: int,
) -> list[int]:
    """단순이동평균 교차 전략의 보유 신호(0 또는 1)를 계산한다.

    Args:
        prices: 오름차순으로 정렬된 가격 시계열.
        short_window: 단기 이동평균 기간 (거래일 수, 1 이상).
        long_window: 장기 이동평균 기간 (short_window보다 커야 함).

    Returns:
        prices와 동일한 길이의 신호 리스트. 인덱스 i의 값은 i번째
        거래일 종가까지의 데이터로 계산한 보유 여부를 의미한다.

    Raises:
        InvalidStrategyParameterError: window 값이 유효하지 않은 경우.
    """
    if short_window < 1 or long_window < 1:
        raise InvalidStrategyParameterError(
            f"short_window/long_window는 1 이상이어야 합니다: "
            f"short_window={short_window}, long_window={long_window}"
        )
    if short_window >= long_window:
        raise InvalidStrategyParameterError(
            f"short_window는 long_window보다 작아야 합니다: "
            f"short_window={short_window}, long_window={long_window}"
        )

    closes = [point.close for point in prices]
    signals: list[int] = []
    for i in range(len(closes)):
        if i + 1 < long_window:
            signals.append(0)
            continue
        short_avg = _simple_moving_average(closes, i, short_window)
        long_avg = _simple_moving_average(closes, i, long_window)
        signals.append(1 if short_avg > long_avg else 0)
    return signals


def _simple_moving_average(closes: list[float], end_index: int, window: int) -> float:
    """closes[end_index - window + 1 .. end_index] 구간의 평균을 계산한다."""
    start_index = end_index - window + 1
    window_values = closes[start_index : end_index + 1]
    return sum(window_values) / window
