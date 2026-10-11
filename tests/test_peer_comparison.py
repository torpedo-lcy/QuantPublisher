from __future__ import annotations

from quantpublisher.analysis.peer_comparison import (
    MIN_SAMPLE,
    PeerInput,
    compute_peer_comparisons,
)


def _stock(
    code: str,
    value: float | None,
    *,
    market: str = "KOSPI",
    industry: str | None = "26110",
    metric: str = "roe",
    basis: str | None = "2025",
) -> PeerInput:
    return PeerInput(code, market, industry, {metric: value}, {metric: basis})


def _metric(result, code: str, key: str = "roe", group: str = "market"):
    return next(m for m in getattr(result[code], group).metrics if m.key == key)


def _ten(**kwargs) -> list[PeerInput]:
    return [_stock(f"{i:06d}", float(i), **kwargs) for i in range(1, 11)]


def test_rank_is_largest_first_and_median_is_group_median() -> None:
    result = compute_peer_comparisons(_ten())

    top = _metric(result, "000010")
    bottom = _metric(result, "000001")
    assert (top.rank, top.median, top.sample) == (1, 5.5, 10)
    assert bottom.rank == 10


def test_equal_values_share_a_rank() -> None:
    stocks = [_stock(f"{i:06d}", 5.0 if i <= 3 else float(i)) for i in range(1, 11)]

    result = compute_peer_comparisons(stocks)

    # 값: 5.0이 네 개(1,2,3,5번), 4.0, 6~10. 5.0보다 큰 값은 다섯 개라 공동 6위다.
    assert _metric(result, "000001").rank == _metric(result, "000002").rank == 6
    assert _metric(result, "000005").rank == 6
    assert _metric(result, "000004").rank == 10  # 4.0보다 큰 값이 아홉 개


def test_group_below_min_sample_has_no_median_or_rank() -> None:
    result = compute_peer_comparisons(_ten()[: MIN_SAMPLE - 1])

    metric = _metric(result, "000005")
    assert (metric.median, metric.rank, metric.sample) == (None, None, 9)
    assert metric.value == 5.0


def test_non_positive_per_and_pbr_are_excluded_but_roe_keeps_negatives() -> None:
    per_values = [-3.0, 0.0] + [float(i) for i in range(1, 11)]
    stocks = [_stock(f"{i:06d}", v, metric="per") for i, v in enumerate(per_values, start=1)]

    result = compute_peer_comparisons(stocks)

    loss = _metric(result, "000001", "per")
    assert loss.value == -3.0 and loss.rank is None  # 값은 보이되 순위에서 제외
    assert loss.sample == 10
    assert _metric(result, "000012", "per").rank == 1

    roe = [_stock(f"{i:06d}", float(v)) for i, v in enumerate(range(-5, 5), start=1)]
    negative = _metric(compute_peer_comparisons(roe), "000001")
    assert negative.rank == 10 and negative.sample == 10


def test_only_same_basis_is_compared() -> None:
    stocks = _ten() + [_stock("999999", 100.0, basis="2024")]

    result = compute_peer_comparisons(stocks)

    odd = _metric(result, "999999")
    assert (odd.rank, odd.median, odd.sample) == (None, None, 1)
    assert _metric(result, "000010").sample == 10  # 다른 기준 시점 종목은 섞이지 않는다


def test_missing_values_and_bases_are_skipped() -> None:
    stocks = _ten() + [_stock("888888", None), _stock("777777", 50.0, basis=None)]

    result = compute_peer_comparisons(stocks)

    assert _metric(result, "000010").sample == 10
    assert _metric(result, "888888").rank is None
    assert _metric(result, "777777").rank is None


def test_industry_group_uses_three_digits_when_large_enough() -> None:
    stocks = _ten(industry="26110") + [_stock("500001", 1.0, industry="26210")]

    result = compute_peer_comparisons(stocks)

    industry = result["000001"].industry
    assert industry is not None and (industry.key, industry.size) == ("261", 10)


def test_industry_group_widens_to_two_digits_then_gives_up() -> None:
    small_three_digit = [_stock(f"{i:06d}", float(i), industry=f"26{i % 3}00") for i in range(1, 11)]
    widened = compute_peer_comparisons(small_three_digit)["000001"].industry
    assert widened is not None and (widened.key, widened.size) == ("26", 10)

    too_small = compute_peer_comparisons(small_three_digit[:9])["000001"]
    assert too_small.industry is None
    assert too_small.market is not None  # 시장 비교는 남는다


def test_unknown_or_malformed_industry_codes_have_no_industry_group() -> None:
    for code in (None, "", "2", "A26", " "):
        result = compute_peer_comparisons([_stock("000001", 1.0, industry=code)])
        assert result["000001"].industry is None


def test_market_groups_are_separate() -> None:
    stocks = _ten(market="KOSPI") + [
        _stock(f"{i:06d}", float(i), market="KOSDAQ", industry=None) for i in range(100, 105)
    ]

    result = compute_peer_comparisons(stocks)

    kospi = result["000001"].market
    kosdaq = result["000100"].market
    assert kospi is not None and (kospi.key, kospi.size) == ("KOSPI", 10)
    assert kosdaq is not None and (kosdaq.key, kosdaq.size) == ("KOSDAQ", 5)
    assert _metric(result, "000100").rank is None  # KOSDAQ 표본 5개 < 10
