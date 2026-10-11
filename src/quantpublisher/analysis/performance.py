"""전기 대비 실적 변화를 분류하는 순수 함수 (Task 018).

DB나 외부 API를 읽지 않는다. 금액(매출액, 영업이익, 순이익)의 당기/전기 값을
받아 증가/감소/흑자전환/적자전환/적자 지속 중 어디에 해당하는지 분류한다.
문장 만들기는 표현 계층(report/markdown.py)이 담당한다.

값이 결측이면 분류하지 않고 None을 반환한다. 전기 값이 0이면 변화율을
계산할 수 없으므로 UNDEFINED로 분류한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChangeKind(str, Enum):
    """전기 대비 변화 유형."""

    INCREASE = "increase"  # 전기, 당기 모두 흑자(양수)이고 당기가 더 큼
    DECREASE = "decrease"  # 전기, 당기 모두 흑자(양수)이고 당기가 더 작음
    UNCHANGED = "unchanged"  # 값이 같음
    TURNED_PROFIT = "turned_profit"  # 전기 적자(또는 0) -> 당기 흑자
    TURNED_LOSS = "turned_loss"  # 전기 흑자 -> 당기 적자
    LOSS_NARROWED = "loss_narrowed"  # 둘 다 적자, 적자 폭 축소
    LOSS_WIDENED = "loss_widened"  # 둘 다 적자, 적자 폭 확대
    UNDEFINED = "undefined"  # 전기가 0이라 비교할 수 없음 (당기도 0이면 UNCHANGED)


@dataclass(frozen=True, slots=True)
class Change:
    """전기 대비 변화.

    Attributes:
        kind: 변화 유형.
        rate: 변화율(%). 전기, 당기 모두 양수일 때(INCREASE, DECREASE)만 의미가 있고,
            그 밖에는 None이다. 적자가 섞인 경우 변화율은 오해를 부르므로 계산하지 않는다.
    """

    kind: ChangeKind
    rate: float | None = None


def classify_change(current: float | None, previous: float | None) -> Change | None:
    """당기와 전기 금액으로 변화 유형을 분류한다. 둘 중 하나라도 결측이면 None."""
    if current is None or previous is None:
        return None
    if current == previous:
        return Change(ChangeKind.UNCHANGED)
    if previous == 0:
        return Change(ChangeKind.TURNED_PROFIT if current > 0 else ChangeKind.TURNED_LOSS)
    if previous > 0 and current > 0:
        rate = (current - previous) / previous * 100
        return Change(ChangeKind.INCREASE if rate > 0 else ChangeKind.DECREASE, rate)
    if previous > 0:  # current <= 0
        return Change(ChangeKind.TURNED_LOSS)
    if current > 0:  # previous < 0
        return Change(ChangeKind.TURNED_PROFIT)
    if current == 0:  # previous < 0
        return Change(ChangeKind.LOSS_NARROWED)
    # 둘 다 음수
    return Change(ChangeKind.LOSS_NARROWED if current > previous else ChangeKind.LOSS_WIDENED)
