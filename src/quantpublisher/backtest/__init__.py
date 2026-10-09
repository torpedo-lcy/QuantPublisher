"""quantpublisher.backtest 패키지.

작은 단일 전략(단순이동평균 교차)에 대한 재현 가능한 백테스트를 제공한다.

이 패키지는 다음을 하지 않는다.
- DB 직접 접근 (가격 시계열은 호출자가 PricePoint 리스트로 전달한다)
- 크롤링
- Git push / Hugo 실행
"""

from quantpublisher.backtest.engine import run_backtest
from quantpublisher.backtest.models import BacktestResult, EquityPoint, PricePoint, Trade
from quantpublisher.backtest.strategy import moving_average_crossover_signals

__all__ = [
    "BacktestResult",
    "EquityPoint",
    "PricePoint",
    "Trade",
    "moving_average_crossover_signals",
    "run_backtest",
]
