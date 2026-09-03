from __future__ import annotations

import dataclasses

import pytest

from quantpublisher.analysis.metrics import calculate_eps, calculate_roe
from quantpublisher.database.models import Security
from quantpublisher.report import StockMetrics, StockReport, build_stock_report


def _sample_security() -> Security:
    return Security(stock_code="005930", name="Samsung Electronics", market="KOSPI")


def test_build_stock_report_contains_stock_identity() -> None:
    security = _sample_security()
    metrics = StockMetrics(roe=10.0, eps=1000.0)

    report = build_stock_report(security, metrics)

    assert report.stock_code == "005930"
    assert report.name == "Samsung Electronics"
    assert report.market == "KOSPI"


def test_build_stock_report_carries_metrics_through_unchanged() -> None:
    metrics = StockMetrics(roe=10.0, eps=1000.0)

    report = build_stock_report(_sample_security(), metrics)

    assert report.metrics is metrics
    assert report.metrics.roe == 10.0
    assert report.metrics.eps == 1000.0


def test_build_stock_report_uses_provided_generated_at() -> None:
    report = build_stock_report(
        _sample_security(),
        StockMetrics(),
        generated_at="2026-01-01T00:00:00+00:00",
    )

    assert report.generated_at == "2026-01-01T00:00:00+00:00"


def test_build_stock_report_defaults_generated_at_when_not_given() -> None:
    report = build_stock_report(_sample_security(), StockMetrics())

    assert report.generated_at
    assert "T" in report.generated_at


def test_build_stock_report_uses_analysis_metrics_functions() -> None:
    metrics = StockMetrics(
        roe=calculate_roe(net_income=1000, equity=10000),
        eps=calculate_eps(net_income=1_000_000, shares_outstanding=1000),
    )

    report = build_stock_report(_sample_security(), metrics)

    assert report.metrics.roe == 10.0
    assert report.metrics.eps == 1000.0


def test_stock_metrics_defaults_are_none() -> None:
    metrics = StockMetrics()

    assert metrics.roe is None
    assert metrics.per is None
    assert metrics.revenue_growth_rate is None


def test_stock_report_is_immutable() -> None:
    report = build_stock_report(_sample_security(), StockMetrics())

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.stock_code = "000000"  # type: ignore[misc]


def test_stock_metrics_is_immutable() -> None:
    metrics = StockMetrics(roe=10.0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        metrics.roe = 20.0  # type: ignore[misc]


def test_stock_report_repr_includes_stock_code() -> None:
    report: StockReport = build_stock_report(_sample_security(), StockMetrics())

    assert "005930" in repr(report)
