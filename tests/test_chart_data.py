from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from quantpublisher.database.models import PriceDaily
from quantpublisher.report.chart_data import (
    build_price_chart_data,
    render_chart_json,
    write_price_chart_json,
)


def _price(trade_date: str, close: float | None, volume: float | None = 100.0) -> PriceDaily:
    return PriceDaily("005930", trade_date, 1.0, 2.0, 0.5, close, volume)  # type: ignore[arg-type]


def test_build_price_chart_data_uses_epoch_days_and_compact_numbers() -> None:
    data = build_price_chart_data(
        "005930", [_price("1970-01-02", 70000.0, 10.0), _price("1970-01-05", 70500.5, 20.0)]
    )

    assert data == {"code": "005930", "t": [1, 4], "c": [70000, 70500.5], "v": [10, 20]}
    assert isinstance(data["c"][0], int)  # type: ignore[index]


def test_build_price_chart_data_epoch_day_round_trips_to_trade_date() -> None:
    data = build_price_chart_data("005930", [_price("2026-10-08", 1.0)])

    assert data is not None
    assert date.fromordinal(date(1970, 1, 1).toordinal() + data["t"][0]).isoformat() == "2026-10-08"  # type: ignore[index]


def test_build_price_chart_data_skips_rows_without_close_and_defaults_volume() -> None:
    data = build_price_chart_data(
        "005930", [_price("2026-10-07", None), _price("2026-10-08", 5.0, None)]
    )

    assert data is not None
    assert data["c"] == [5]
    assert data["v"] == [0]


def test_build_price_chart_data_returns_none_without_usable_rows() -> None:
    assert build_price_chart_data("005930", []) is None
    assert build_price_chart_data("005930", [_price("2026-10-08", None)]) is None


def test_render_chart_json_is_compact_and_deterministic() -> None:
    data = build_price_chart_data("005930", [_price("2026-10-08", 5.0)])
    assert data is not None

    text = render_chart_json(data)

    assert text == render_chart_json(data)
    assert " " not in text
    assert json.loads(text) == data


def test_write_price_chart_json_skips_unchanged_and_none(tmp_path: Path) -> None:
    prices = [_price("2026-10-08", 5.0)]
    path = write_price_chart_json("005930", prices, tmp_path)
    assert path == tmp_path / "005930.json"
    before = path.stat().st_mtime_ns

    write_price_chart_json("005930", prices, tmp_path)

    assert path.stat().st_mtime_ns == before
    assert write_price_chart_json("000660", [], tmp_path) is None
    assert not (tmp_path / "000660.json").exists()
