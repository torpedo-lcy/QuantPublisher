from __future__ import annotations

import pytest

from quantpublisher.analysis.performance import Change, ChangeKind, classify_change


@pytest.mark.parametrize(
    ("current", "previous", "kind"),
    [
        (150.0, 100.0, ChangeKind.INCREASE),
        (50.0, 100.0, ChangeKind.DECREASE),
        (100.0, 100.0, ChangeKind.UNCHANGED),
        (0.0, 0.0, ChangeKind.UNCHANGED),
        (10.0, -5.0, ChangeKind.TURNED_PROFIT),
        (10.0, 0.0, ChangeKind.TURNED_PROFIT),
        (-10.0, 5.0, ChangeKind.TURNED_LOSS),
        (0.0, 5.0, ChangeKind.TURNED_LOSS),
        (-1.0, -5.0, ChangeKind.LOSS_NARROWED),
        (0.0, -5.0, ChangeKind.LOSS_NARROWED),
        (-9.0, -5.0, ChangeKind.LOSS_WIDENED),
    ],
)
def test_classify_change_kinds(current: float, previous: float, kind: ChangeKind) -> None:
    result = classify_change(current, previous)

    assert result is not None
    assert result.kind == kind


def test_classify_change_rate_only_when_both_positive() -> None:
    assert classify_change(150.0, 100.0) == Change(ChangeKind.INCREASE, 50.0)
    assert classify_change(50.0, 100.0) == Change(ChangeKind.DECREASE, -50.0)
    assert classify_change(10.0, -5.0).rate is None  # type: ignore[union-attr]
    assert classify_change(-9.0, -5.0).rate is None  # type: ignore[union-attr]


def test_classify_change_returns_none_for_missing_values() -> None:
    assert classify_change(None, 100.0) is None
    assert classify_change(100.0, None) is None
